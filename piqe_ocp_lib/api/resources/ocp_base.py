from collections import namedtuple
import logging
import os
from threading import RLock
import warnings

import jmespath
from kubernetes import config
from kubernetes.client.rest import ApiException
from openshift.dynamic import DynamicClient, Resource
from urllib3.exceptions import InsecureRequestWarning
import yaml

from piqe_ocp_lib import __loggername__
from piqe_ocp_lib.api.constants import CLUSTER_VERSION_OPERATOR_ID

warnings.simplefilter("ignore", InsecureRequestWarning)

logger = logging.getLogger(__loggername__)


Version = namedtuple("Version", ["major", "minor", "patch"])


class OcpBase:
    """
    This dict will hold kubeconfig as key and DynamicClient object as value
    """

    _dyn_clients = {}

    """
    This dict will hold kubeconfig as key and  kubernetes object, k8_client as value
    """
    k8s_clients = {}

    # For thread safe
    _lock = RLock()

    def __init__(self, kube_config_file=None):
        """
        The init method for the base class
        :return: None
        """
        # Lock the thread in case of multi-threading
        with OcpBase._lock:
            self.kube_config_file = kube_config_file or os.environ.get("KUBECONFIG")

    @property
    def k8s_client(self):
        """
        Return k8s_client instance for specific openshift cluster based on kube_config_file attribute
        :return: Instance of K8s_client
        """
        if self.kube_config_file and self.kube_config_file not in OcpBase.k8s_clients:
            OcpBase.k8s_clients[self.kube_config_file] = config.new_client_from_config(str(self.kube_config_file))
        return OcpBase.k8s_clients.get(self.kube_config_file)

    @property
    def dyn_client(self):
        """
        Return dyn_client instance for specific openshift cluster based on kube_config_file attribute
        :return: Instance of DynamicClient
        """
        # Lock the thread in case of multi-threading
        with OcpBase._lock:
            if OcpBase._dyn_clients.get(self.kube_config_file) is None:
                OcpBase._dyn_clients[self.kube_config_file] = DynamicClient(self.k8s_client)
            return OcpBase._dyn_clients.get(self.kube_config_file)

    @property
    def ocp_version(self):
        """
        Return tuple of cluster version in the form (major, minor, z-stream)
        :return: (tuple) cluster version
        """
        return self._get_ocp_version()

    @property
    def provider(self):
        """
        Return the name of the infrastructure provider if discoverable
        :return: (str) The infrastructure provider as described by
        spec.platformSpec.type in the Infrastructure resource
        """
        return self._get_infrastructure_provider()

    def _get_ocp_version(self):
        """
        Method that discovers the server version and returns it in the form of a tuple
        containing major and minor version.
        :return: A tuple containing the major version in string format at index 0,
                 the minor version in string format at index 1,
                 and z-stream version at index 2
        """
        try:
            client = self.dyn_client.resources.get(api_version="config.openshift.io/v1", kind="ClusterVersion")
            version = client.get(name=CLUSTER_VERSION_OPERATOR_ID)
        except ApiException as e:
            logger.exception(f"Exception was encountered while trying to obtain cluster version: {e}")
            return None

        version_query = "sort_by(status.history[?state=='Completed'], &completionTime)[::-1].version"
        version = jmespath.search(version_query, version.to_dict())
        if "nightly" in version[0]:
            version = [(version[0].split("-"))[0]]
        return Version(*map(int, version[0].split(".")))

    def _get_infrastructure_provider(self):
        """
        Returns the infrastructure provided for this cluster by
        instpecting the Infastructure resource.
        :return: (str) The name of the infrastructure provider or None
        """
        provider = ""
        try:
            api_response = self.dyn_client.resources.search(api_version="config.openshift.io/v1", kind="Infrastructure")
            assert isinstance(api_response, list)
        except ApiException as e:
            logger.exception(f"Exception was encountered while trying to get the infrastructure resource: {e}")
        if api_response and isinstance(api_response[0], Resource) and api_response[0].kind == "Infrastructure":
            api_response = api_response[0]
            infra_obj = api_response.get()
            try:
                provider = infra_obj.items[0].spec.platformSpec.type
            except KeyError:
                logger.error(f"Could not access the platformSpec key in Infrastructure: \n{infra_obj}")
        return provider

    def get_data_from_kubeconfig_v4(self):
        """
        Get required data from kubeconfig file provided by openshift
        - API Server URL
        - Access Token
        :return: (dict) Return dict in form of kubeconfig_data
        """
        kubeconfig_data = dict()
        api_server_url = None

        with open(self.kube_config_file) as f:
            kcfg = yaml.load(f, Loader=yaml.FullLoader)

            # Get API server URL
            logger.info("Find API Server URL from kubeconfig file")
            if "clusters" in kcfg:
                clusters = kcfg["clusters"]
                for cluster in clusters:
                    if "server" in cluster["cluster"]:
                        api_server_url = cluster["cluster"]["server"]
                    if api_server_url:
                        break
            logger.info("API Server URL : %s", api_server_url)
            kubeconfig_data["api_server_url"] = api_server_url

        return kubeconfig_data
