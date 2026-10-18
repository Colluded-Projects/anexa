import os

# Must be set before anexa.config is imported anywhere.
os.environ["ANEXA_STORE_BACKEND"] = "memory"
os.environ["ANEXA_CELERY_EAGER"] = "true"
os.environ["ANEXA_SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-hs256"

import pytest

from anexa.config import get_settings
from anexa.repos import Repos
from anexa.store import MemoryStore, set_store


@pytest.fixture
def settings():
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture(scope="session")
def _lite_client():
    """One embedded FalkorDB for the whole session (starting it is slow)."""
    import tempfile

    from redislite.falkordb_client import FalkorDB

    return FalkorDB(os.path.join(tempfile.mkdtemp(prefix="anexa-test-"), "test.db"))


@pytest.fixture
def store(settings, request):
    """A fresh store installed as the process-wide store: in-memory by default,
    a real embedded FalkorDB when ANEXA_TEST_FALKOR_LITE=1."""
    if os.environ.get("ANEXA_TEST_FALKOR_LITE"):
        from anexa.store.falkor import FalkorStore

        client = request.getfixturevalue("_lite_client")
        store = FalkorStore(client)
        set_store(store)
        yield store
        set_store(None)
        for graph in client.list_graphs():
            store.delete_graph(graph)
        return
    store = MemoryStore()
    set_store(store)
    yield store
    set_store(None)


@pytest.fixture
def repos(store, settings):
    return Repos(store, settings)
