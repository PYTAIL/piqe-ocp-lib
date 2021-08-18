import logging
from typing import List, Optional, Tuple, Union, Dict

from kubernetes.client.rest import ApiException

from piqe_ocp_lib import __loggername__
from piqe_ocp_lib.api.ocp_exceptions import UnsupportedInstallMode
from piqe_ocp_lib.api.resources import OcpBase, OcpProjects
from piqe_ocp_lib.api.resources.ocp_operators import (
    ClusterServiceVersion,
    OperatorGroup,
    OperatorhubPackages,
    Subscription,
)

logger = logging.getLogger(__loggername__)


class OperatorInstaller(OcpBase):
    def __init__(self, kube_config_file: Optional[str] = None):
        super().__init__(kube_config_file=kube_config_file)
        self.og_obj = OperatorGroup(kube_config_file=self.kube_config_file)
        self.sub_obj = Subscription(kube_config_file=self.kube_config_file)
        self.ohp_obj = OperatorhubPackages(kube_config_file=self.kube_config_file)
        self.proj_obj = OcpProjects(kube_config_file=self.kube_config_file)
        self.csv = ClusterServiceVersion(self.kube_config_file)

    def _derive_install_mode_from_target_namespaces(self, target_namespaces: Union[List[str], str]) -> str:
        """
        Length of target_namespaces list enables us to derive the appropriate install mode
        Look at the length of the target_namespaces list:
            1. If the wildcard '*' is used, it gets interpreted as'AllNamespaces'.
            2. If it's zero, we return 'OwnNamespace'.
            3. If length is 1, we return 'SingleNamespace'.
            4. If length > 1, we return 'MultiNamespace'.
        """
        if target_namespaces == "*":
            install_mode = "AllNamespaces"
        else:
            target_namespaces_count = len(target_namespaces)
            if target_namespaces_count == 0:
                install_mode = "OwnNamespace"
            elif target_namespaces_count == 1:
                install_mode = "SingleNamespace"
            elif target_namespaces_count > 1:
                install_mode = "MultiNamespace"
        return install_mode

    def _create_operator_namespace(self, operator_name: str, operator_namespace: str, channel_name: str) -> str:
        """
        A helper method that creates the namespace where both the subscription and operator
        group objects will be created to install an operator.
        """
        if not operator_namespace:
            operator_namespace = self.ohp_obj.get_channel_suggested_namespace(operator_name, channel_name)
        if not operator_namespace:
            operator_namespace = f"openshift-{operator_name}"
        assert self.proj_obj.create_a_namespace(operator_namespace)
        return operator_namespace

    def _create_og(
        self, operator_name: str, channel_name: str, operator_namespace: str, target_namespaces: Union[list, str]
    ) -> Tuple[str, str]:
        """
        A helper method that creates the operator group in the generated operator namespace
        """
        derived_install_mode = self._derive_install_mode_from_target_namespaces(target_namespaces)
        if not self.ohp_obj.is_install_mode_supported_by_channel(operator_name, channel_name, derived_install_mode):
            err_msg = f"The specified channel doesn't support {channel_name} installs"
            logger.exception(err_msg)
            raise UnsupportedInstallMode(err_msg)
        else:
            operator_namespace = self._create_operator_namespace(operator_name, operator_namespace, channel_name)
            og_name = f"{operator_name}-og"
            assert self.og_obj.create_operator_group(og_name, operator_namespace, target_namespaces)
        return og_name, operator_namespace

    def add_operator_to_cluster(
        self,
        operator_name: str,
        channel_name: str = "",
        operator_namespace: str = "",
        target_namespaces: Union[List[str], str] = [],
    ) -> bool:
        """
        Install an operator in a list of target namespaces
        :param operator_name: (required | str) The name of the operator to be installed
        :param channel_name: (Optional | str) The name of the channel we want to subscribe to. This is what determines
                             what version of the operator we want to install. If left unspecified, the operator default
                             channel is selected.
        :param operator_namespace: (optional | str) The name of the namespace that will hold the subscription
                                   and operatorgroup objects. If left unspecified, a suggested namespace name
                                   will be searched for in the channel object. If not found, a namespace will be
                                   created with the naming convention 'openshift-<operator-name>'
        :param target_namespaces: (optional | list) A list of namespace/Projects where want the
                                   operator to be enabled in. If left unspecified, the operartor
                                   will be installed/enabled throughout the entire cluster.
        :return: (bool) True if install is successful, False otherwise.
        """
        pkg_obj = self.ohp_obj.get_package_manifest(operator_name)
        if not pkg_obj:
            err_msg = f"A package manifest for {operator_name} could not be found"
            logger.exception(err_msg)
            raise ApiException(err_msg)
        if not channel_name:
            channel_name = self.ohp_obj.get_package_default_channel(operator_name)
        _, operator_namespace = self._create_og(operator_name, channel_name, operator_namespace, target_namespaces)
        sub_resp = self.sub_obj.create_subscription(operator_name, channel_name, operator_namespace)
        return sub_resp is not None

    def is_operator_installed(self, operator_name: str, operator_namespace: str) -> Optional[Dict]:
        """
        Check if operator is installed and returned true or false
        :param operator_name: name of the operator.
        return: object of spec of respective operator's subscription
        """
        all_sub_resp_obj = self.sub_obj.get_all_subscription()
        for i in range(0,len(all_sub_resp_obj.items)):
            if operator_name in str(all_sub_resp_obj.items[i]):
                target_item = i
        csv_name = self.ohp_obj.get_package_channel_by_name(operator_name,
                   all_sub_resp_obj.items[target_item]['spec']['channel']).currentCSV
        assert 'channel' in all_sub_resp_obj.items[target_item]['spec'].keys()
        assert 'sourceNamespace' in all_sub_resp_obj.items[target_item]['spec'].keys()
        assert 'startingCSV' in all_sub_resp_obj.items[target_item]['spec'].keys()
        assert 'name' in all_sub_resp_obj.items[target_item]['spec'].keys()
        assert all_sub_resp_obj.items[target_item]['spec']['name'] == operator_name
        assert all_sub_resp_obj.items[target_item]['status']['state'] == 'AtLatestKnown'
        assert self.csv.is_cluster_service_version_present(csv_name, operator_namespace)
        return all_sub_resp_obj.items[target_item]['spec']    

    def get_version_of_operator(self, operator_name: str, operator_namespace: str) -> Optional[str]:
        """
        Get the version of operator if operator is installed
        :param operator_name: name of the operator.
        return: version of the operator
        """
        ioi = self.is_operator_installed(operator_name, operator_namespace)
        if ioi is not None:
            return self.ohp_obj.get_package_channel_by_name(operator_name, 
             ioi['channel'])['currentCSVDesc']['version']
        else:
            logger.info("%s operator is not installed", operator_name)
            return None   

    def get_channel_of_operator(self, operator_name: str, operator_namespace: str) -> Optional[str]:
        """
        Get the channel of operator if operator is installed
        :param operator_name: name of the operator.
        return: channel of the operator
        """
        ioi = self.is_operator_installed(operator_name, operator_namespace)
        if ioi is not None:
            return ioi['channel']
        else:
            logger.info("%s operator is not installed", operator_name)
            return None
          
    def delete_operator_from_cluster(self, operator_name: str, namespace: str) -> bool:
        """
        Uninstall an operator from a cluster
        :param operator_name: name of the operator
        :param namespace: name of the namespace the operator is installed
        :return: success or failure
        """
        try:
            subscription = self.sub_obj.get_subscription(operator_name, namespace)
            csv_name = subscription.status.currentCSV
        except ApiException:
            logger.error("Failed to retrieve subscription")
            return False

        try:
            self.sub_obj.delete_subscription(operator_name, namespace)
            self.csv.delete_cluster_service_version(csv_name, namespace)
        except ApiException:
            logger.error(f"Failed to uninstall operator {operator_name}")
            return False

        return True
