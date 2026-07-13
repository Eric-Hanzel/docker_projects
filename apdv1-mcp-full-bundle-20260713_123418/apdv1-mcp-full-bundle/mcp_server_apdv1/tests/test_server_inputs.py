import unittest

from apdv1_mcp_server.server import _normalize_target


class ServerInputTest(unittest.TestCase):
    def test_default_delivery_mode_is_portable_deliverable(self):
        self.assertEqual(
            _normalize_target({"url": "https://example.com/project"}),
            {
                "url": "https://example.com/project",
                "delivery_mode": "portable-deliverable",
                "portable_final_required": True,
            },
        )

    def test_local_run_is_supported(self):
        self.assertEqual(
            _normalize_target({"url": "https://example.com/project", "delivery_mode": "local-run"}),
            {
                "url": "https://example.com/project",
                "delivery_mode": "local-run",
                "portable_final_required": False,
            },
        )

    def test_legacy_image_format_maps_to_image_bundle(self):
        self.assertEqual(
            _normalize_target({"url": "https://example.com/project", "delivery_format": "image"}),
            {
                "url": "https://example.com/project",
                "delivery_mode": "portable-deliverable",
                "portable_final_required": True,
                "image_bundle": True,
            },
        )

    def test_invalid_delivery_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            _normalize_target({"url": "https://example.com/project", "delivery_mode": "portable"})


if __name__ == "__main__":
    unittest.main()
