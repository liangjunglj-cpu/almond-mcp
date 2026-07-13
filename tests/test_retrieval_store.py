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


if __name__ == "__main__":
    unittest.main()
