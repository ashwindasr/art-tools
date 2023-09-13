import asyncio
import os
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

from pyartcd import constants
from pyartcd.pipelines import brew_scan_osh


class TestInitialBuildPlan(unittest.IsolatedAsyncioTestCase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.brew_scan_osh: brew_scan_osh.OshScan = self.default_pipeline()

    def setUp(self) -> None:
        self.ocp4 = self.default_pipeline()

    @staticmethod
    def default_pipeline() -> brew_scan_osh.OshScan:
        return brew_scan_osh.OshScan(
            runtime=MagicMock(dry_run=False),
            email="",
            version="4.15"
        )

    @patch("pyartcd.pipelines.brew_scan_osh.OshScan._get_ocp_candidate_tags", autospec=True,
           return_value=["rhaos-{MAJOR}.{MINOR}-rhel-8-candidate", "rhaos-{MAJOR}.{MINOR}-rhel-9-candidate",
                         "rhaos-{MAJOR}.{MINOR}-ironic-rhel-9-candidate"])
    async def test_format_candidate_tags(self, _):
        await self.brew_scan_osh._set_candidate_tags()
        self.assertEqual(self.brew_scan_osh.tags, ['rhaos-4.15-rhel-8-candidate', 'rhaos-4.15-rhel-9-candidate',
                                                   'rhaos-4.15-ironic-rhel-9-candidate'])

