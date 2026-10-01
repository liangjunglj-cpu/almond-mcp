"""Design code profiles: loading, validation, and their effect on the native check."""
import copy
import json

import pytest

from almond_mcp import design_codes as dc
from almond_mcp import native_structure as ns
from almond_mcp import structure_study as st
from tests.test_stability import portal_model

EUROCODE = json.loads((dc.BUILT_IN / "eurocode.json").read_text(encoding="utf-8"))


@pytest.fixture
def user_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ALMOND_DESIGN_CODE_DIR", str(tmp_path))
    return tmp_path


def profile(pid="test-na", **values):
    """A user profile: the Eurocode document with some values replaced (unverified)."""
    doc = copy.deepcopy(EUROCODE)
    doc.update(id=pid, name=f"Test {pid}", basis="Test National Annex")
    for k, v in values.items():
        doc["parameters"][k] = {"value": v, "source": f"Test NA for {k}", "verified": False}
    return doc


def write(folder, doc, name=None):
    (folder / (name or doc["id"] + ".json")).write_text(json.dumps(doc), encoding="utf-8")


def model(d=219.1, t=8.0):
    return dict(portal_model(d, t), status="ok", shells=0)


def test_builtin_eurocode_is_the_default_and_fully_sourced():
    code = dc.load(None)
    assert code.id == "eurocode" and not code.unverified and code.origin == "built-in"
    assert (code.gamma_G, code.gamma_Q, code.psi_0, code.xi) == (1.35, 1.5, 0.7, 0.85)
    assert (code.gamma_M0, code.gamma_M1, code.deflection_limit_ratio) == (1.0, 1.0, 250.0)
    assert all(code.sources[k] for k in code.values)
    assert dc.load("off").factored is False


def test_default_results_are_unchanged_by_the_mechanism():
    """The Eurocode profile reproduces the previously hard-coded EN 1990 recommended values."""
    assert ns.combinations("en1990", "6.10") == (ns.SLS, [("ULS 6.10", {"G": 1.35, "Q": 1.5})])
    assert ns.combinations("en1990", "6.10ab")[1] == [("ULS 6.10a", {"G": 1.35, "Q": 1.05}),
                                                       ("ULS 6.10b", {"G": 1.1475, "Q": 1.5})]
    assert ns.combinations("en1990", None)[1][0][0] == "ULS 6.10"           # the profile's default
    assert ns.combinations("unfactored")[1] == ns.combinations("en1990", None, "off")[1] == \
        [("Unfactored", {"G": 1.0, "Q": 1.0})]


def test_user_profile_changes_factors_and_is_reported(user_dir):
    write(user_dir, profile(xi=0.925, uls_expression="6.10ab", gamma_M1=1.1, deflection_limit_ratio=360))
    code = dc.load("test-na")
    assert code.origin.endswith("test-na.json") and set(code.unverified) == {"xi", "uls_expression", "gamma_M1",
                                                                             "deflection_limit_ratio"}
    assert ns.combinations("en1990", None, code)[1][1] == ("ULS 6.10b", {"G": round(0.925 * 1.35, 6), "Q": 1.5})
    kw = dict(structure_type="frame", load_kn=40, fixed_supports=False, self_weight=False)
    base = ns.validate(model(), **kw)
    na = ns.validate(model(), design_code="test-na", **kw)
    assert na["design_code"]["id"] == "test-na" and na["design_code"]["uls_expression"] == "6.10ab"
    assert na["results"]["deflection_limit_mm"] == pytest.approx(base["results"]["deflection_limit_mm"] * 250 / 360, abs=1e-3)
    assert any("not yet verified" in w for w in na["warnings"])
    assert any("Design code: Test test-na" in a for a in na["assumptions"])
    # the request for 6.10 is overridden by a profile that prescribes 6.10a/b, and said so
    forced = ns.validate(model(), design_code="test-na", uls="6.10", **kw)
    assert forced["results"]["utilization_combination"].startswith("ULS 6.10")
    assert any("prescribes ULS expression 6.10ab" in w for w in forced["warnings"])


def test_gamma_m_scales_member_utilization(user_dir):
    write(user_dir, profile("strict", gamma_M0=1.1, gamma_M1=1.1))
    kw = dict(structure_type="frame", load_kn=2000, fixed_supports=True, self_weight=False, stability="off")
    u0 = ns.validate(model(), **kw)["results"]["utilization_ratio"]
    u1 = ns.validate(model(), design_code="strict", **kw)["results"]["utilization_ratio"]
    assert u1 == pytest.approx(1.1 * u0, rel=2e-3)


def test_off_is_unfactored_with_unit_material_factors():
    kw = dict(structure_type="frame", load_kn=40, fixed_supports=True, self_weight=False)
    off = ns.validate(model(), design_code="off", **kw)
    old = ns.validate(model(), design_basis="unfactored", **kw)
    assert off["results"]["utilization_ratio"] == old["results"]["utilization_ratio"]
    assert off["design_code"]["id"] == "off" and off["results"]["utilization_combination"].startswith("Unfactored")


@pytest.mark.parametrize("change, needle", [
    ({"id": "Bad Id"}, "id"), ({"id": "off"}, "id"), ({"schema_version": 2}, "schema_version"),
    ({"name": ""}, "name"),
])
def test_invalid_documents_are_rejected(change, needle):
    doc = profile()
    doc.update(change)
    with pytest.raises(ValueError, match=needle):
        dc.parse(doc)


@pytest.mark.parametrize("key, value, needle", [
    ("gamma_G", 0.9, "between"), ("gamma_Q", "1.5", "between"), ("psi_0", 1.5, "between"),
    ("uls_expression", "6.10c", "one of"), ("deflection_limit_ratio", 20, "between"),
    ("gamma_M1", True, "between"), ("imposed_floor_kn_m2", {"A": -1}, "use categories"),
    ("gamma_G", None, "no value"),
])
def test_out_of_range_values_are_rejected(key, value, needle):
    with pytest.raises(ValueError, match=needle):
        dc.parse(profile(**{key: value}))


def test_missing_source_and_unknown_parameters_are_rejected():
    doc = profile()
    doc["parameters"]["gamma_G"]["source"] = ""
    with pytest.raises(ValueError, match="source"):
        dc.parse(doc)
    doc = profile()
    doc["parameters"]["gamma_X"] = {"value": 1, "source": "x"}
    with pytest.raises(ValueError, match="unknown"):
        dc.parse(doc)
    doc = profile()
    del doc["parameters"]["gamma_M1"]
    with pytest.raises(ValueError, match="missing parameter gamma_M1"):
        dc.parse(doc)


def test_discovery_reports_bad_files_and_protects_builtin_ids(user_dir):
    write(user_dir, profile("eurocode"), "mine.json")                  # cannot replace the built-in
    (user_dir / "broken.json").write_text("{not json", encoding="utf-8")
    write(user_dir, profile("good"))
    listing = dc.listing()
    ids = [p["id"] for p in listing["profiles"]]
    assert ids[0] == "eurocode" and ids[-1] == "off" and "good" in ids
    assert any("already defined" in p for p in listing["problems"])
    assert any(p.startswith("broken.json") for p in listing["problems"])
    assert dc.load("eurocode").origin == "built-in"
    with pytest.raises(ValueError, match="Unknown design code 'nope'"):
        dc.load("nope")


def test_study_uses_profiles_and_ping_lists_them(user_dir):
    write(user_dir, profile("test-na", deflection_limit_ratio=360))
    out = st.run({"model": model(), "settings": {"design_code": "test-na", "load_kn": 40, "fixed_rotations": False}})
    assert out["validation"]["design_code"]["id"] == "test-na"
    assert out["draw"]["deflection_limit_ratio"] == 360 and "design_code" not in out["draw"]["result"]
    assert st.run({"model": model(), "settings": {"design_code": "nope"}})["status"] == "error"
    import io
    reply = io.StringIO()
    st.main(io.StringIO('{"ping": true}'), reply)
    codes = json.loads(reply.getvalue())["design_codes"]
    assert codes["default"] == "eurocode" and {"eurocode", "test-na", "off"} <= {p["id"] for p in codes["profiles"]}


def test_timber_and_aluminium_are_flagged_indicative():
    kw = dict(structure_type="frame", load_kn=10, fixed_supports=True, self_weight=False)
    timber = ns.validate(model(), material="Wood", **kw)
    assert timber["confidence"] == "low" and any("EN 1995" in w for w in timber["warnings"])
    steel = ns.validate(model(), material="Steel", **kw)
    assert steel["confidence"] == "high" and not any("indicative" in w for w in steel["warnings"])
    assert not any(a.startswith("Linear-elastic, first-order") or a.startswith("Rigid joints")
                   for a in steel["assumptions"])
