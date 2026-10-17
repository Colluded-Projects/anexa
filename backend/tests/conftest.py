import os

# Must be set before orgraph.config is imported anywhere.
os.environ["ORGRAPH_STORE_BACKEND"] = "memory"
os.environ["ORGRAPH_CELERY_EAGER"] = "true"
os.environ["ORGRAPH_SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-hs256"

import pytest

from orgraph.config import get_settings
from orgraph.repos import Repos
from orgraph.store import MemoryStore, set_store


@pytest.fixture
def settings():
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture(scope="session")
def _lite_client():
    """One embedded FalkorDB for the whole session (starting it is slow)."""
    import tempfile

    from redislite.falkordb_client import FalkorDB

    return FalkorDB(os.path.join(tempfile.mkdtemp(prefix="orgraph-test-"), "test.db"))


@pytest.fixture
def store(settings, request):
    """A fresh store installed as the process-wide store: in-memory by default,
    a real embedded FalkorDB when ORGRAPH_TEST_FALKOR_LITE=1."""
    if os.environ.get("ORGRAPH_TEST_FALKOR_LITE"):
        from orgraph.store.falkor import FalkorStore

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
