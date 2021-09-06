from kubernetes.client.rest import ApiException
from piqe_ocp_lib.tests.helpers import config
from piqe_ocp_lib import __loggername__
import logging
from piqe_ocp_lib.api.crd.local_storage_operator import LocalStorageOperator, LocalVolume
import pytest

from piqe_ocp_lib.api.resources.ocp_operators import ClusterServiceVersion

logger = logging.getLogger(__loggername__)

@pytest.fixture(scope="session")
def get_test_objects(get_kubeconfig):
    """
    Prepare the test artifacts as an object and pass it as
    a fixture.
    """

    class TestObjects:
        def __init__(self):
            self.csv_obj = ClusterServiceVersion(kube_config_file=get_kubeconfig)
            self.lso = LocalStorageOperator(kube_config_file=get_kubeconfig)
            self.lv = LocalVolume(kube_config_file=get_kubeconfig)

    test_objs = TestObjects()
    return test_objs

    @pytest.fixture(scope="module")
    def local_storage_operator(get_kubeconfig) -> LocalStorageOperator:
        return LocalStorageOperator(kube_config_file=get_kubeconfig)

    @pytest.fixture(scope="module")
    def local_volume(get_kubeconfig) -> LocalVolume:
        return LocalVolume(kube_config_file=get_kubeconfig)

class TestLocalStorageOperator:
    def test_create_local_volume(self, get_test_objects):
        assert get_test_objects.lv.create_local_volume() is not None

    def test_get_local_volume(self, get_test_objects):
        api_response = get_test_objects.lv.get_local_volume()
        assert len(api_response.items) !=0

    def test_delete_local_volume(self, get_test_objects):
        assert get_test_objects.lv.delete_local_volume() is not None

    def test_watch_local_volume(self, get_test_objects):
        assert get_test_objects.lv.watch_local_volume('example') is not False
