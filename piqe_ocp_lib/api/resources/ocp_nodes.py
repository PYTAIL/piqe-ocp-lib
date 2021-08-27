import logging
import subprocess
from typing import Optional

from kubernetes.client.rest import ApiException
from openshift.dynamic.resource import ResourceInstance, ResourceList

from piqe_ocp_lib import __loggername__
from piqe_ocp_lib.api.resources.ocp_base import OcpBase

logger = logging.getLogger(__loggername__)


class OcpNodes(OcpBase):
    """
    OcpNodes Class extends OcpBase and encapsulates all methods
    related to managing Openshift nodes.
    :param kube_config_file: A kubernetes config file.
    :return: None
    """

    def __init__(self, kube_config_file=None):
        self.kube_config_file = kube_config_file
        OcpBase.__init__(self, kube_config_file=self.kube_config_file)
        self.api_version = "v1"
        self.kind = "Node"
        self.ocp_nodes = self.dyn_client.resources.get(api_version=self.api_version, kind=self.kind)

    def get_all_nodes(self, label_selector=None):
        """
        Method that returns a list of node objects
        :param label_selector: Used to return a a list of nodes based on the provided label(s)
        :return: V1NodeList on success. None on failure.
        """
        node_object_list = None
        try:
            node_object_list = self.ocp_nodes.get(label_selector=label_selector)
        except ApiException as e:
            logger.error("Exception when calling method list_node: %s\n", e)
        return node_object_list

    def get_all_node_names(self):
        """
        Method that returns a list of all node names based on node objects
        :return: List of unfiltered node names on success. None on failure.
        """
        node_names = []
        try:
            node_object_list = self.get_all_nodes(label_selector=None)
            for node in node_object_list.items:
                node_names.append(node.metadata.name)
        except ApiException as e:
            logger.error("Exception encountered while gathering node names: %s\n", e)
        return node_names

    def get_a_node(self, node_name):
        """
        Method returns a node object by name

        :param node_name: The name of the node.
        :return: V1Node on success. None on failure.
        """
        node_object = None
        try:
            node_object = self.ocp_nodes.get(name=node_name)
        except ApiException as e:
            logger.error("Exception encountered while getting a node by name: %s\n", e)
        return node_object

    def get_total_memory_in_bytes(self):
        """
        Get total cluster memory by adding memory from all Nodes
        :return: (int) Total memory in byte on success OR 0 on Failure
        """
        total_memory_in_bytes = 0
        node_response = self.get_all_nodes()
        if node_response:
            for node in node_response.items:
                if node["status"]["capacity"]["memory"][-2:] == "Ki":
                    total_memory_in_bytes += int(node["status"]["capacity"]["memory"][:-2]) * 1024
                if node["status"]["capacity"]["memory"][-2:] == "Mi":
                    total_memory_in_bytes += int(node["status"]["capacity"]["memory"][:-2]) * (1024 * 1024)
                if node["status"]["capacity"]["memory"][-2:] == "Gi":
                    total_memory_in_bytes += int(node["status"]["capacity"]["memory"][:-2]) * (1024 * 1024)
            logger.info("Total memory in bytes : %s", total_memory_in_bytes)
        return total_memory_in_bytes

    def is_node_ready(self, node_name, timeout=300):
        """
        Check if a node has reached a Ready state
        :param node_name: (str) The node name
        :param timeout: (int) The time limit for polling status. Defaults to 300
        :return: (bool) True if it's Ready OR False otherwise
        """
        field_selector = f"metadata.name={node_name}"
        for event in self.ocp_nodes.watch(field_selector=field_selector, timeout=timeout):
            conditions_list = event["object"]["status"]["conditions"]
            latest_event = conditions_list[-1]
            if conditions_list and latest_event["type"] == "Ready" and latest_event["status"] == "True":
                logger.debug(f"Node {node_name} has reached 'Ready' state")
                return True
            else:
                logger.debug(
                    "Waiting for node {} to reach 'Ready' state."
                    "Reason: {}".format(node_name, latest_event["message"])
                )
        return False

    def is_node_deleted(self, node_name, timeout=300):
        """
        Check if a node was successfully deleted
        :param node_name: (str) The node name
        :param timeout: (int) The time limit for polling status. Defaults to 300
        :return: (bool) True if it's deleted OR False otherwise
        """
        if self.get_a_node(node_name) is None:
            logger.info(f"Node {node_name} is not present")
            return True
        else:
            logger.debug("Node seems to be present, let's watch")
            field_selector = f"metadata.name={node_name}"
            for event in self.ocp_nodes.watch(field_selector=field_selector, timeout=timeout):
                if self.get_a_node(node_name):
                    logger.debug("Node is still present")
                    logger.debug("Node state is: {}".format(event["object"]["status"]["conditions"][-1]["message"]))
                    continue
                else:
                    logger.debug("Node is no longer here")
                    return True
        return False

    def label_a_node(self, node_name, labels):
        """
        Method that patches a node as a means to apply a label to it.
        :param node_name: The name of the node to patch
        :param labels: A dictionary containing the key,val labels
        :return: A V1DeploymentConfig object
        """
        body = {"metadata": {"labels": labels}}
        api_response = None
        try:
            api_response = self.ocp_nodes.patch(name=node_name, body=body)
        except ApiException as e:
            logger.error("Exception while patching nodes: %s\n", e)
        return api_response

    def get_node_status(self, node_name):
        """
        Return the status of a node based on the condition type Ready.
        :param node_name:
        :return: The status for the condition. Either True or False
        """
        node_object = None
        try:
            node_object = self.ocp_nodes.get(name=node_name)
            for condition in node_object.status.conditions:
                condition_type = condition.get("type")
                if condition_type == "Ready":
                    return condition.get("status")
        except ApiException as e:
            logger.error("Exception encountered while determining the node condition: %s\n", e)
        return node_object

    def get_node_roles(self, node_name):
        """
        Return the roles assigned to the nodes by looking for the following:
        node-role.kubernetes.io/master: ''
        node-role.kubernetes.io/worker: ''
        :param node_name: The node to examine
        :return: List containing the awssigned roles. Currently Master and/or Worker.
        """
        node_role = []
        try:
            node_object = self.ocp_nodes.get(name=node_name)
            # labels are returned as tuples
            for label in node_object.metadata.labels:
                if label[0] == "node-role.kubernetes.io/master":
                    node_role.append("Master")
                if label[0] == "node-role.kubernetes.io/worker":
                    node_role.append("Worker")
        except ApiException as e:
            logger.error("Exception encountered while getting a node by name: %s\n", e)
        return node_role

    def execute_command_on_a_node(self, node_name, command_to_execute):
        """
        Executes the provided command on the specified node_name.
        :param node_name:  The name of the node on which command gets executed
        :param command_to_execute:
        :return:  return code, stdout, stderr of the command executed
        """
        # Pod Name
        pod_name = "execute-on-%s" % node_name

        # Check if pod exists
        command = "kubectl get pods | grep %s" % pod_name
        logger.info("Executing command: %s", command)
        subp = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = subp.communicate()
        ret = subp.returncode
        logger.info(
            "Command - %s - execution status:\n" "RETCODE: %s\nSTDOUT: %s\nSTDERR: %s\n", command, ret, out, err
        )
        if ret != 0:
            # Spin a new container for the node
            container_definition = (
                """
                {
                  "spec": {
                    "hostPID": true,
                    "hostNetwork": true,
                    "nodeSelector": { "kubernetes.io/hostname": "%s" },
                    "tolerations": [{
                      "operator": "Exists"
                    }],
                    "containers": [
                      {
                        "name": "nsenter",
                        "image": "alexeiled/nsenter:2.34",
                        "command": [
                          "/nsenter", "--all", "--target=1", "--", "su", "-"
                        ],
                        "stdin": true,
                        "tty": true,
                        "securityContext": {
                          "privileged": true
                        },
                        "resources": {
                          "requests": {
                            "cpu": "10m"
                          }
                        }
                      }
                    ]
                  }
                }"""
                % node_name
            )
            command = "kubectl run %s --restart=Never --image " "overriden --overrides '%s'" % (
                pod_name,
                container_definition,
            )
            logger.info("Executing command : %s", command)
            subp = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = subp.communicate()
            ret = subp.returncode
            logger.info(
                "Command - %s - execution status:\n" "RETCODE: %s\nSTDOUT: %s\nSTDERR: %s\n", command, ret, out, err
            )
            if ret != 0:
                return ret, out, err
        # Execute the command
        command = f"kubectl exec {pod_name} -- {command_to_execute}"
        logger.info("Executing command: %s", command)
        subp = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = subp.communicate()
        ret = subp.returncode
        logger.info(
            "Command - %s - execution status:\n" "RETCODE: %s\nSTDOUT: %s\nSTDERR: %s\n", command, ret, out, err
        )
        return ret, out, err

    def get_master_nodes(self) -> Optional[ResourceList]:
        """
        Method that returns a list of master node objects
        :param label_selector: Used to return a a list of nodes based on the provided label(s)
        :return: V1NodeList on success. None on failure.
        """
        master_node_object_list = None
        try:
            master_node_object_list = self.get_all_nodes(label_selector="node-role.kubernetes.io/master")
        except ApiException as e:
            logger.error("Exception when calling method list_node: %s\n", e)
        return master_node_object_list

    def get_worker_nodes(self) -> Optional[ResourceList]:
        """
        Method that returns a list of worker node objects
        :param label_selector: Used to return a a list of nodes based on the provided label(s)
        :return: V1NodeList on success. None on failure.
        """
        worker_node_object_list = None
        try:
            worker_node_object_list = self.get_all_nodes(label_selector="node-role.kubernetes.io/worker")
        except ApiException as e:
            logger.error("Exception when calling method list_node: %s\n", e)
        return worker_node_object_list

    def is_node_schedulable(self, node_name: str) -> bool:
        """
        Return the node schedulable status
        :param node_name:
        :return: Node schedulable status, Either True or False. None on failure.
        """
        node_object = None
        try:
            node_object = self.ocp_nodes.get(name=node_name)
            if node_object.spec.unschedulable:
                logger.info("Node %s status is unschedulable" % node_name)
                return False
            else:
                logger.info("Node %s status is schedulable" % node_name)
                return True
        except ApiException as e:
            logger.error("Exception encountered while determining the node schedulable status: %s\n", e)
        return node_object

    def mark_node_schedulable(self, node_name: str) -> Optional[ResourceInstance]:
        """
        Return node which was marked as schedulable
        :param node_name:
        :return: A V1Node object. None on failure.
        """
        api_response = None
        body = {"spec": {"unschedulable": False}}
        schedulable_status = self.is_node_schedulable(node_name)
        if schedulable_status:
            logger.info("Node %s is already schedulable" % node_name)
            api_response = self.ocp_nodes.get(name=node_name)
        else:
            try:
                api_response = self.ocp_nodes.patch(name=node_name, body=body)
                logger.info("Node %s marked schedulable" % node_name)
            except ApiException as e:
                logger.error("Exception encountered while marking node as schedulable: %s\n", e)
        return api_response

    def mark_node_unschedulable(self, node_name: str) -> Optional[ResourceInstance]:
        """
        Return node which was marked unschedulable
        :param node_name:
        :return: A V1Node object. None on failure.
        """
        api_response = None
        body = {"spec": {"unschedulable": True}}
        unschedulable_status = self.is_node_schedulable(node_name)
        if not unschedulable_status:
            logger.info("Node %s already unscheduled" % node_name)
            api_response = self.ocp_nodes.get(name=node_name)
        else:
            try:
                api_response = self.ocp_nodes.patch(name=node_name, body=body)
                logger.info("Node %s marked unschedulable" % node_name)
            except ApiException as e:
                logger.error("Exception encountered while marking node unschedulable: %s\n", e)
        return api_response
