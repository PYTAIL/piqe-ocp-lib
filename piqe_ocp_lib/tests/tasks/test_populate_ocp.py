import logging
import os
from unittest import mock

from kubernetes.client.rest import ApiException
import pytest

from piqe_ocp_lib import __loggername__
from piqe_ocp_lib.api.resources.ocp_operators import ClusterServiceVersion, Subscription
from piqe_ocp_lib.api.tasks.operator_ops import OperatorInstaller
from piqe_ocp_lib.api.tasks.populate_cluster.populate_cluster import PopulateOcpCluster

logger = logging.getLogger(__loggername__)


@pytest.fixture(scope="session")
def populate_ocp_cluster(ocp_smoke_args):
    """
    A fixture that provides an instance of the populate_ocp_cluster class
    """
    if ocp_smoke_args.cluster_config:
        cluster_config = ocp_smoke_args.cluster_config
    elif "WORKSPACE" in os.environ and os.environ["WORKSPACE"]:
        cluster_config = "%s/piqe_ocp_lib/tests/" "config/smoke_ocp_config.yaml" % os.environ["WORKSPACE"]
    else:
        raise ValueError(
            "A path to the cluster config yaml was expected, or a WORKSPACE env variable"
            " to find the default template"
        )
    logger.info("Config Template Location : %s", cluster_config)
    logger.info("Kubeconfig  Location : %s", ocp_smoke_args.kubeconfig)
    return PopulateOcpCluster(k8=ocp_smoke_args.kubeconfig, ocp_cluster_config=cluster_config)


@pytest.mark.integration
class TestPopulateOcpCluster:
    @pytest.mark.populate
    def test_populate_cluster(self, populate_ocp_cluster, ocp_smoke_args):
        logger.info("Starting Populate OCP cluster tests...")
        populate_ocp_cluster.populate_cluster(filter=ocp_smoke_args.label_filter)
        logger.info("Is populate OCP succeed : %s", populate_ocp_cluster.is_populate_successful)
        assert populate_ocp_cluster.is_populate_successful is True

    @pytest.mark.longevity
    def test_ocp_longevity(self, populate_ocp_cluster, ocp_smoke_args):
        """ Testcase to test if running longevity tests on existing cluster is successful """
        is_longevity_successful = False
        try:
            is_longevity_successful = populate_ocp_cluster.longevity(
                ocp_smoke_args.span, scale_replicas=ocp_smoke_args.replicas
            )
        except Exception as e:
            logger.error("Exception while running longevity: %s", e.message)
        logger.info("Is longevity completed successfully? : %s", is_longevity_successful)
        assert is_longevity_successful is True

    @pytest.mark.cleanup
    def test_cleanup(self, populate_ocp_cluster, ocp_smoke_args):
        logger.info("Started cleanup tests...")
        cleanup_project_list = populate_ocp_cluster.cleanup(filter=ocp_smoke_args.label_filter)
        assert len(cleanup_project_list) == 0


class TestOperatorIntaller:
    @pytest.mark.unit
    @mock.patch.object(Subscription, "get_subscription")
    @mock.patch.object(Subscription, "delete_subscription")
    @mock.patch.object(ClusterServiceVersion, "delete")
    def test_delete_operator_from_cluster(self, mock_csv, mock_delete_sub, mock_get_sub, get_kubeconfig):
        expected_operator_name = "foo-name"
        expected_operator_namespace = "foo-namespace"
        expected_csv = mock.Mock()
        expected_csv.status.currentCSV = "some-version"
        mock_get_sub.return_value = expected_csv
        installer = OperatorInstaller(get_kubeconfig)

        installer.delete_operator_from_cluster(expected_operator_name, expected_operator_namespace)

        mock_get_sub.assert_called_once_with(expected_operator_name, expected_operator_namespace)
        mock_delete_sub.assert_called_once_with(expected_operator_name, expected_operator_namespace)
        mock_csv.assert_called_once_with("some-version", expected_operator_namespace)

    @pytest.mark.unit
    @mock.patch.object(Subscription, "get_subscription", side_effect=[ApiException])
    def test_delete_operator_from_cluster_failed_to_get_sub(self, mock_get_sub, get_kubeconfig, caplog):
        caplog.set_level(logging.ERROR)

        expected_operator_name = "foo-name"
        expected_operator_namespace = "foo-namespace"

        installer = OperatorInstaller(get_kubeconfig)

        installer.delete_operator_from_cluster(expected_operator_name, expected_operator_namespace)
        mock_get_sub.assert_called_once_with(expected_operator_name, expected_operator_namespace)

        assert "Failed to retrieve subscription" in [m.message for m in caplog.records]

    @pytest.mark.unit
    @mock.patch.object(Subscription, "get_subscription")
    @mock.patch.object(Subscription, "delete_subscription", side_effect=[ApiException])
    @mock.patch.object(ClusterServiceVersion, "delete")
    def test_delete_operator_from_cluster_failed_to_delete_sub(self, mock_get_sub, get_kubeconfig, caplog):
        caplog.set_level(logging.ERROR)

        expected_operator_name = "foo-name"
        expected_operator_namespace = "foo-namespace"

        installer = OperatorInstaller(get_kubeconfig)

        installer.delete_operator_from_cluster(expected_operator_name, expected_operator_namespace)
        mock_get_sub.assert_called_once_with(expected_operator_name, expected_operator_namespace)

        assert f"Failed to uninstall operator {expected_operator_name}" in [m.message for m in caplog.records]
