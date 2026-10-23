"""Importing this package registers every collector in `base.REGISTRY`."""

from radar.collectors import ct, meta_ads, serp, social, stores, telegram  # noqa: F401
from radar.collectors.base import REGISTRY, run_collector  # noqa: F401
