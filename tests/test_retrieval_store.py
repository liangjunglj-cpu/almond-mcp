import json
import tempfile
import unittest
from pathlib import Path

from almond_mcp.retrieval_store import AlmondStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RetrievalStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = AlmondStore(Path(self.temp_dir.name) / "state.sqlite3")
        ikea_manifest = json.loads(
            (PROJECT_ROOT / "IkeaFurniturefiles" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        drawing_manifest = json.loads(
            (PROJECT_ROOT / "DrawingAssetfiles" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        for asset in ikea_manifest["assets"]:
            asset["file_available"] = (
                PROJECT_ROOT / "IkeaFurniturefiles" / asset["file"]
            ).is_file()
        for asset in drawing_manifest["assets"]:
            asset["file_available"] = (
                PROJECT_ROOT / "DrawingAssetfiles" / asset["file"]
            ).is_file()
        # Both libraries grow over time; keep the manifest counts so the
        # assertions below track the data instead of hardcoding totals.
        self.ikea_asset_count = len(ikea_manifest["assets"])
        self.drawing_asset_count = len(drawing_manifest["assets"])
        self.store.sync_assets(
            drawing_manifest["assets"],
            library_id="drawing_assets",
        )
        self.store.sync_assets(ikea_manifest["assets"], library_id="ikea")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_fts_and_structured_filters_return_compact_cards(self):
        chairs = self.store.search_assets(
            query="reading chair",
            library_id="ikea",
            category="chair",
        )
        self.assertGreaterEqual(chairs["total"], 1)
        self.assertTrue(all("asset_id" in asset for asset in chairs["assets"]))
        self.assertTrue(all("warehouse_url" not in asset for asset in chairs["assets"]))

        compact_sofa = self.store.search_assets(
            query="compact living room",
            library_id="ikea",
            category="sofa",
            max_width_mm=2000,
            exact_dimensions_only=True,
        )
        self.assertEqual(
            [asset["asset_id"] for asset in compact_sofa["assets"]],
            ["ikea-sg-klippan-s49010615"],
        )

        context_tree = self.store.search_assets(
            query="landscape tree",
            library_id="drawing_assets",
            category="tree",
        )
        self.assertGreaterEqual(context_tree["total"], 1)
        self.assertEqual(context_tree["assets"][0]["source_class"], "drawing_asset")
        self.assertEqual(context_tree["assets"][0]["brand"], "Generic")
        self.assertEqual(context_tree["assets"][0]["library_id"], "drawing_assets")

        ikea_tree = self.store.search_assets(
            query="landscape tree",
            library_id="ikea",
        )
        self.assertEqual(ikea_tree["total"], 0)
        self.assertEqual(
            self.store.asset_stats("ikea")["total"], self.ikea_asset_count
        )
        self.assertEqual(
            self.store.asset_stats("drawing_assets")["total"],
            self.drawing_asset_count,
        )

    def test_scene_revisions_and_rtree_collisions(self):
        scene = self.store.create_scene("Collision test")
        scene_id = scene["scene_id"]
        room = self.store.upsert_room(
            scene_id,
            "Living room",
            [0, 0, 0, 5000, 5000, 3000],
        )
        first = self.store.upsert_instance(
            scene_id,
            "ikea-sg-kallax-70351886",
            1000,
            1000,
            room_id=room["room_id"],
        )
        second = self.store.upsert_instance(
            scene_id,
            "ikea-sg-poang-s19240788",
            1000,
            1000,
            room_id=room["room_id"],
        )
        invalid = self.store.validate_scene(scene_id)
        self.assertFalse(invalid["passed"])
        self.assertEqual(invalid["collision_count"], 1)

        moved = self.store.upsert_instance(
            scene_id,
            "ikea-sg-poang-s19240788",
            3000,
            1000,
            room_id=room["room_id"],
            instance_id=second["instance_id"],
        )
        valid = self.store.validate_scene(scene_id)
        self.assertTrue(valid["passed"])
        self.assertGreater(moved["revision"], first["revision"])

    def test_generation_plan_enforces_dependencies(self):
        plan = self.store.create_generation_plan(
            "Furnish a compact apartment",
            scope="interior",
        )
        plan_id = plan["plan_id"]
        with self.assertRaises(ValueError):
            self.store.update_plan_step(
                plan_id,
                "retrieve_assets",
                "completed",
            )

        self.store.update_plan_step(plan_id, "inspect_rooms", "completed")
        updated = self.store.update_plan_step(
            plan_id,
            "retrieve_assets",
            "completed",
            output_refs=["ikea-sg-klippan-s49010615"],
        )
        steps = {step["step_id"]: step for step in updated["steps"]}
        self.assertEqual(steps["retrieve_assets"]["status"], "completed")
        self.assertEqual(
            steps["retrieve_assets"]["output_refs"],
            ["ikea-sg-klippan-s49010615"],
        )

        drawing_plan = self.store.create_generation_plan(
            "Produce a technical axonometric",
            scope="drawing",
        )
        self.assertEqual(
            drawing_plan["steps"][0]["step_id"],
            "freeze_scene",
        )
        self.assertEqual(
            drawing_plan["steps"][-1]["step_id"],
            "validate_drawing",
        )


class SceneLedgerFixesTests(RetrievalStoreTests):
    """Regressions from the 2026-07-14 stress test (issues #3 and #4)."""

    def test_upsert_room_by_name_updates_instead_of_duplicating(self):
        scene = self.store.create_scene("Upsert test")
        first = self.store.upsert_room(
            scene["scene_id"], "L1 Office", [0, 0, 18000, 6000, 4000, 21000]
        )
        second = self.store.upsert_room(
            scene["scene_id"], "L1 Office", [0, 0, 0, 6000, 4000, 3000]
        )
        self.assertEqual(first["room_id"], second["room_id"])
        self.assertEqual(self.store.get_scene(scene["scene_id"])["rooms"], 1)

    def test_instance_z_defaults_to_room_floor(self):
        scene = self.store.create_scene("Storey test")
        room = self.store.upsert_room(
            scene["scene_id"], "L1", [0, 0, 18000, 10000, 6000, 21000]
        )
        instance = self.store.upsert_instance(
            scene["scene_id"],
            "ikea-sg-klippan-s49010615",
            x_mm=3000,
            y_mm=2000,
            room_id=room["room_id"],
        )
        report = self.store.validate_scene(scene["scene_id"])
        self.assertEqual(report["outside_room_count"], 0, report)
        # explicit z still wins
        grounded = self.store.upsert_instance(
            scene["scene_id"],
            "ikea-sg-klippan-s49010615",
            x_mm=3000,
            y_mm=2000,
            z_mm=0,
            room_id=room["room_id"],
            instance_id=instance["instance_id"],
        )
        report = self.store.validate_scene(scene["scene_id"])
        self.assertEqual(report["outside_room_count"], 1)
        self.assertEqual(report["outside_room"][0]["failing_axes"], ["z"])

    def test_remove_instance_and_room(self):
        scene = self.store.create_scene("Removal test")
        room = self.store.upsert_room(
            scene["scene_id"], "L1", [0, 0, 0, 10000, 6000, 3000]
        )
        instance = self.store.upsert_instance(
            scene["scene_id"],
            "ikea-sg-klippan-s49010615",
            x_mm=3000,
            y_mm=2000,
            room_id=room["room_id"],
        )
        keep = self.store.upsert_instance(
            scene["scene_id"],
            "ikea-sg-kallax-70351886",
            x_mm=6000,
            y_mm=2000,
            room_id=room["room_id"],
        )
        removed = self.store.remove_instance(scene["scene_id"], instance["instance_id"])
        self.assertGreater(removed["revision"], 0)
        self.assertEqual(self.store.get_scene(scene["scene_id"])["instances"], 1)
        with self.assertRaises(KeyError):
            self.store.remove_instance(scene["scene_id"], instance["instance_id"])

        room_removed = self.store.remove_room(scene["scene_id"], room["room_id"])
        self.assertEqual(room_removed["orphaned_instances"], 1)
        self.assertEqual(self.store.get_scene(scene["scene_id"])["rooms"], 0)
        # orphaned instance survives
        self.assertEqual(self.store.get_scene(scene["scene_id"])["instances"], 1)
        self.assertTrue(keep["instance_id"])


class ValidationHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = AlmondStore(Path(self.temp_dir.name) / "state.sqlite3")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_record_and_list_validation_runs(self):
        request = {"structure_type": "truss", "load_kn": 25.0, "material": "S355"}
        result = {
            "status": "pass",
            "passed": True,
            "confidence": "high",
            "verdict": "[KARAMBA 3.1 API, HIGH CONFIDENCE] PASSED",
            "warnings": ["No anchor points declared; supporting 3 lowest-Z node(s)."],
            "results": {
                "analysis_method": "api",
                "span_m": 6.0,
                "max_deflection_mm": 0.4,
                "deflection_limit_mm": 24.0,
                "utilization_ratio": 0.01,
                "max_stress_mpa": 7.5,
                "yield_stress_mpa": 355.0,
                "reactions_kn": 25.002,
            },
        }
        run_id = self.store.record_validation_run(request, result, ["guid-a", "guid-b"])
        self.assertGreater(run_id, 0)

        runs = self.store.list_validation_runs()
        self.assertEqual(len(runs), 1)
        run = runs[0]
        self.assertEqual(run["structure_type"], "truss")
        self.assertEqual(run["material"], "S355")
        self.assertEqual(run["analysis_method"], "api")
        self.assertEqual(run["confidence"], "high")
        self.assertTrue(run["passed"])
        self.assertEqual(run["member_count"], 2)
        self.assertAlmostEqual(run["reactions_kn"], 25.002)
        self.assertEqual(len(run["warnings"]), 1)
        self.assertEqual(run["guids"], ["guid-a", "guid-b"])

        # newest first
        self.store.record_validation_run(request, result, ["guid-c"])
        runs = self.store.list_validation_runs()
        self.assertEqual(runs[0]["member_count"], 1)


if __name__ == "__main__":
    unittest.main()
