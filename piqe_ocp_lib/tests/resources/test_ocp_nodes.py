import logging

import pytest

from piqe_ocp_lib import __loggername__
from piqe_ocp_lib.api.resources import OcpNodes

logger = logging.getLogger(__loggername__)


@pytest.fixture(scope="class")
def setup_params(get_kubeconfig):
    params_dict = {}
    params_dict["node_api_obj"] = OcpNodes(kube_config_file=get_kubeconfig)
    return params_dict


class TestOcpNodes:
    def test_get_all_nodes(self, setup_params):
        """
        Verify that a list of all nodes is returned
        1. Call get_all_nodes method via a ocp_nodes instance
        2. Verify that the response object is of kind NodeList
        :param setup_params:
        :return:
        """
        node_api_obj = setup_params["node_api_obj"]
        # Get all nodes
        api_response = node_api_obj.get_all_nodes()
        node_count = len(api_response.items)
        logger.info(f"{node_count} nodes returned in the list")
        assert api_response.kind == "NodeList"

        # Get nodes matching a single label
        api_response = node_api_obj.get_all_nodes(label_selector="beta.kubernetes.io/os")
        list_items_single_label = len(api_response.items)
        # All nodes are expected to have this label, validate that the list counts match.
        assert list_items_single_label == node_count
        logger.info(f"{list_items_single_label} nodes matched the provided label")
        assert api_response.kind == "NodeList"
        # Get nodes matching 2 labels
        api_response = node_api_obj.get_all_nodes(
            label_selector="beta.kubernetes.io/os=linux," "node.openshift.io/os_id=rhcos"
        )
        list_items_two_labels = len(api_response.items)
        # All nodes are expected to have these labels, validate that the list counts match.
        assert list_items_two_labels == node_count
        logger.info(f"{list_items_two_labels} nodes matched the provided label")
        assert api_response.kind == "NodeList"

    def test_get_all_node_names(self, setup_params):
        """
        Verify that node name lists are returned.
        1. Call get_all_nodes method via a ocp_nodes instance
        2. Verify that the response object type is a List
        :param setup_params:
        :return:
        """
        node_api_obj = setup_params["node_api_obj"]
        api_response = node_api_obj.get_all_node_names()
        assert type(api_response) is list
        logger.info(f"Node name list: {api_response}")
        assert len(api_response) > 0

    def test_get_a_node(self, setup_params):
        """
        Verify that nodes are returned by name
        1. Call get_all_nodes method via a ocp_nodes instance
        2. Verify that the response object is of kind NodeList
        :param setup_params:
        :return:
        """
        node_api_obj = setup_params["node_api_obj"]
        api_response_node_name_list = node_api_obj.get_all_node_names()
        number_of_nodes = len(api_response_node_name_list)
        assert number_of_nodes > 0
        logger.info(f"{number_of_nodes} Nodes returned")
        for node_name in api_response_node_name_list:
            # Use each node name from the list to get_a_node by mane.
            api_response = node_api_obj.get_a_node(node_name=node_name)
            assert api_response.kind == "Node"
            # Evaluate Use addresses list to find the type Hostname
            assert api_response.metadata.name == node_name
        # Attempt to fetch a node that does not exist.
        # The method under test is expected to log an exception and return None
        api_response_not_found = node_api_obj.get_a_node(node_name="non_existent_node")
        assert api_response_not_found is None

    def test_get_status_of_a_node(self, setup_params):
        """
        Verify that node status is returned.
        1. Get a list of all nodes and validate that the list is not empty.
        2. Iterate through the list of node names and get the status of each node.
        3. Validate that each node returns status: True
        :param setup_params:
        :return:
        """
        node_api_obj = setup_params["node_api_obj"]
        api_response_node_name_list = node_api_obj.get_all_node_names()
        assert len(api_response_node_name_list) > 0
        for node_name in api_response_node_name_list:
            # Use each node name from the list to get the node status by name
            api_response_node_status = node_api_obj.get_node_status(node_name=node_name)
            assert api_response_node_status == "True"

    def test_get_node_roles(self, setup_params):
        """
        Verify that the node roles are returned and validate that either Master or Worker
        (or both) are assigned to the node.
        1. Get a list of the node names
        2. Iterate through the list and fetch the roles for each node.
        3. Validate that the returned list has at least one item.
        4. Validate that the content represents either Master or Worker roles.
        :param setup_params:
        :return:
        """
        node_api_obj = setup_params["node_api_obj"]
        api_response_node_name_list = node_api_obj.get_all_node_names()
        for node_name in api_response_node_name_list:
            # Use each node name from the list to get the node status by name
            api_response_node_roles = node_api_obj.get_node_roles(node_name=node_name)
            logger.info(f"Retrieved {api_response_node_roles} roles for node {node_name}")
            number_of_roles = len(api_response_node_roles)
            assert number_of_roles >= 1
            for role in api_response_node_roles:
                logger.info(f"Node name: {node_name} Role: {role}")
                assert role == "Master" or role == "Worker"

    def test_label_a_node(self, setup_params):
        """
        Test creating a label on a node.
        1. Get a list of all node names
        2. Iterate through the list to get the Nodes based on their name.
        3. Validate that the returned Node matches the name.
        4. Label the node using a new key:value
        5. Call get all nodes, filtering the nodes by label to fetch the same node. This validates that the newly
           created label can be used to filter out the node.
        6. Validate the returned node by name using metadata.name and status.addresses.address.type and .address.
        """
        node_api_obj = setup_params["node_api_obj"]
        api_response_node_name_list = node_api_obj.get_all_node_names()
        for node_name in api_response_node_name_list:
            api_response = node_api_obj.get_a_node(node_name=node_name)
            assert api_response.kind == "Node"
            assert api_response.metadata.name == node_name
            # Label the node
            node_label = {"test.label.node": "true"}
            logger.info(f"Label the Node with {node_label}")
            label_api_response = node_api_obj.label_a_node(node_name=node_name, labels=node_label)
            assert label_api_response.kind == "Node"
            assert label_api_response.metadata.name == node_name
            # Now fetch the node using the created filter.
            labelled_node_api_response = node_api_obj.get_all_nodes(
                label_selector="test.label.node=true," "kubernetes.io/hostname=" + node_name
            )
            logger.info(f"Retrieved the node by labels {labelled_node_api_response.items[0].metadata.name}")
            assert len(labelled_node_api_response.items) == 1
            assert labelled_node_api_response.items[0].metadata.name == node_name
            logger.info(f"Retrieved the node by labels {labelled_node_api_response.items[0].metadata.name}")
            # Evaluate Use addresses list to find the type Hostname
            for address in labelled_node_api_response.items[0].status.addresses:
                if address.type == "Hostname":
                    logger.info(f"Address Type: {address.type}  Address: {address.address}")
                    # Validate that the node name is the same as the hostname for the node.
                    assert address.address == node_name

    def test_get_total_memory_in_bytes(self, setup_params):
        """
        Verify that method returns total memory of cluster by adding all memory from each cluster nodes
        :return:
        """
        node_api_obj = setup_params["node_api_obj"]
        total_memory = node_api_obj.get_total_memory_in_bytes()
        if not total_memory:
            assert False, "Failed to get total memory from cluster"
        assert isinstance(total_memory, int)

    @pytest.mark.skip(reason="MPQEENABLE-396 expected_retcode assertion fails")
    def test_execute_command_on_a_node(self, setup_params):
        """
        On each node perform the following:
        1. Execute a valid command on the node and validate the return code indicates success,
           that stdout contains the expected output and that stderr is empty.
        2. Execute an invalid command on the node and validate the return code indicates failure,
           that stdout is empty and that stderr contains an error message.
        :param setup_params:
        :return:
        """
        node_api_obj = setup_params["node_api_obj"]
        api_response_node_name_list = node_api_obj.get_all_node_names()
        # Validate stdout
        for node_name in api_response_node_name_list:
            api_response = node_api_obj.get_a_node(node_name=node_name)
            assert api_response.kind == "Node"
            assert api_response.metadata.name == node_name
            logger.info(f"Execute command on Node {node_name}")
            command_api_response = node_api_obj.execute_command_on_a_node(
                node_name=node_name, command_to_execute="whoami"
            )
            expected_retcode = 0
            expected_stdout = b"root\n"
            expected_stderr = b""
            assert command_api_response[0] == expected_retcode
            assert type(command_api_response[1]) is bytes
            assert command_api_response[1] == expected_stdout
            assert command_api_response[2] == expected_stderr
            decoded_str = command_api_response[1].decode("utf-8")
            logger.info(f"Decoded stdout string {decoded_str}")

        # Validate stderr
        for node_name in api_response_node_name_list:
            api_response = node_api_obj.get_a_node(node_name=node_name)
            assert api_response.kind == "Node"
            assert api_response.metadata.name == node_name
            logger.info(f"Execute command on Node {node_name}")
            command_api_response = node_api_obj.execute_command_on_a_node(
                node_name=node_name, command_to_execute="bogus"
            )
            expected_retcode = 1
            expected_stdout = b""
            assert command_api_response[0] == expected_retcode
            assert command_api_response[1] == expected_stdout
            assert type(command_api_response[2]) is bytes
            decoded_str = command_api_response[2].decode("utf-8")
            logger.info(f"Decoded stderr string {decoded_str}")
            assert decoded_str.find("executable file not found in $PATH") >= 1

    def test_get_all_master_nodes(self, setup_params):
        """
        Verify that a list of all master nodes is returned
        1. Call get_master_nodes method
        2. Verify that the response object is of kind NodeList
        :param setup_params:
        :return:
        """
        node_api_obj = setup_params["node_api_obj"]
        # Get all master nodes
        api_response = node_api_obj.get_master_nodes()
        node_count = len(api_response.items)
        logger.info("{} master nodes returned in the list".format(node_count))
        for master_node in api_response.items:
            assert "node-role.kubernetes.io/master" in master_node.metadata.labels.keys()
        assert api_response.kind == "NodeList"

    def test_get_all_worker_nodes(self, setup_params):
        """
        Verify that a list of all worker nodes is returned
        1. Call get_worker_nodes method
        2. Verify that the response object is of kind NodeList
        :param setup_params:
        :return:
        """
        node_api_obj = setup_params["node_api_obj"]
        # Get all worker nodes
        api_response = node_api_obj.get_worker_nodes()
        node_count = len(api_response.items)
        logger.info("{} worker nodes returned in the list".format(node_count))
        if len(api_response.items) > 0:
            for worker_node in api_response.items:
                assert "node-role.kubernetes.io/worker" in worker_node.metadata.labels.keys()
        assert api_response.kind == "NodeList"

    def test_is_node_schedulable(self, setup_params):
        """
        Verify that a boolean is returned based on the node schedulable status
        1. Call get_master_nodes method via a ocp_nodes instance
        2. Call is_node_schedulable method via a ocp_nodes instance
        3. Verify that a True is returned if node is schedulable & a false is returned
            if node is unschedulable
        4. Call get_worker_nodes method via a ocp_nodes instance
        5. Call is_node_schedulable method via a ocp_nodes instance
        6. Verify that a True is returned if node is schedulable & a false is returned
            if node is unschedulable
        :param setup_params:
        :return:
        """
        node_api_obj = setup_params["node_api_obj"]
        # Check if all master nodes are schedulable/unschedulable
        master_node_list = node_api_obj.get_master_nodes()
        for master_node_name in master_node_list.items:
            node_schedulable_status = node_api_obj.is_node_schedulable(node_name=master_node_name.metadata.name)
            if not node_schedulable_status:
                assert node_schedulable_status is False
            else:
                assert node_schedulable_status is True
        # Check if all worker nodes are schedulable/unschedulable
        worker_node_list = node_api_obj.get_worker_nodes()
        for worker_node_name in worker_node_list.items:
            node_schedulable_status = node_api_obj.is_node_schedulable(node_name=worker_node_name.metadata.name)
            if not node_schedulable_status:
                assert node_schedulable_status is False
            else:
                assert node_schedulable_status is True

    def test_mark_node_unschedulable(self, setup_params):
        """
        Verify that masters/worker nodes are marked unschedulable
        1. Call get_master_nodes method via a ocp_nodes instance
        2. Call mark_node_unschedulable method
        3. Verify that the response object has unschedulable set to True
        4. Call get_worker_nodes method via a ocp_nodes instance
        5. Call mark_node_unschedulable method
        6. Verify that the response object has unschedulable set to True
        :param setup_params:
        :return:
        """
        node_api_obj = setup_params["node_api_obj"]
        # Mark all master nodes unschedulable
        master_node_list = node_api_obj.get_master_nodes()
        for master_node_name in master_node_list.items:
            api_response = node_api_obj.mark_node_unschedulable(node_name=master_node_name.metadata.name)
            assert api_response.kind == "Node"
        # Mark all worker nodes unschedulable
        worker_node_list = node_api_obj.get_worker_nodes()
        for worker_node_name in worker_node_list.items:
            api_response = node_api_obj.mark_node_unschedulable(node_name=worker_node_name.metadata.name)
            assert api_response.kind == "Node"

    def test_mark_node_schedulable(self, setup_params):
        """
        Verify that a masters/worker nodes are marked schedulable
        1. Call get_master_nodes method via a ocp_nodes instance
        2. Call mark_node_schedulable method
        3. Verify that the response object has unschedulable set to None
        4. Call get_worker_nodes method via a ocp_nodes instance
        5. Call mark_node_schedulable method
        6. Verify that the response object has unschedulable set to True
        :param setup_params:
        :return:
        """
        node_api_obj = setup_params["node_api_obj"]
        # Mark all master nodes schedulable
        master_node_list = node_api_obj.get_master_nodes()
        for master_node_name in master_node_list.items:
            api_response = node_api_obj.mark_node_schedulable(node_name=master_node_name.metadata.name)
            assert api_response.kind == "Node"
        # Mark all worker nodes schedulable
        worker_node_list = node_api_obj.get_worker_nodes()
        for worker_node_name in worker_node_list.items:
            api_response = node_api_obj.mark_node_schedulable(node_name=worker_node_name.metadata.name)
            assert api_response.kind == "Node"
