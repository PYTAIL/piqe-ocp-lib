import logging

from kubernetes.client.rest import ApiException
from openshift.dynamic.resource import ResourceInstance, ResourceList

from piqe_ocp_lib import __loggername__
from piqe_ocp_lib.api.resources.ocp_base import OcpBase
from piqe_ocp_lib.api.resources.ocp_nodes import OcpNodes

logger = logging.getLogger(__loggername__)
MACHINE_NAMESPACE = "openshift-machine-api"
TIMEOUT = 300


class OcpMachineSet(OcpBase):
    """
    OcpMachineSet class extends OcpBase and encapsulates all methods
    related to managing Openshift Machine Sets.
    :param kube_config_file: A kubernetes config file.
    :return: None
    """

    def __init__(self, kube_config_file=None):
        super().__init__(kube_config_file=kube_config_file)
        self.api_version = "machine.openshift.io/v1beta1"
        self.kind = "MachineSet"
        self.machineset = self.dyn_client.resources.get(api_version=self.api_version, kind=self.kind)
        self.machine = OcpMachines(kube_config_file=kube_config_file)
        self.node = OcpNodes(kube_config_file=kube_config_file)

    def get_machine_sets(self) -> ResourceList:
        """
        Get all Machine sets in a cluster
        :return: MachineSetList on success OR an empty list on failure
        """
        api_response = list()
        try:
            api_response = self.machineset.get(namespace=MACHINE_NAMESPACE)
        except ApiException as e:
            logger.error("Exception while getting all Machine Sets: %s\n", e)

        return api_response

    def get_machine_set(self, machine_set_name: str) -> ResourceInstance:
        """
        Get a Machine set by name
        :param machine_set_name: (str) name of the machine set
        :return: MachineSet object on success OR None on failure
        """
        api_response = None
        try:
            api_response = self.machineset.get(name=machine_set_name, namespace=MACHINE_NAMESPACE)
        except ApiException as e:
            logger.error("Exception while getting Machine set: %s\n", e)

        return api_response

    def get_machine_set_role(self, machine_set_name: str) -> str:
        """
        Get a Machine set role
        :param machine_set_name: (str) name of the machine set
        :return: Machine set role on success OR empty string on failure
        """
        role = ""
        machine_set = self.get_machine_set(machine_set_name)
        role = machine_set.metadata.labels["machine.openshift.io/cluster-api-machine-role"]
        return role

    def is_machine_set_ready(self, machine_set_name: str) -> bool:
        """
        Verify that a Machine reflects the desired number of user specified replicas
        :param machine_set_name: (str) name of the machine set
        :return: (bool) True when readyReplicas == replicas OR False otherwise
        """
        field_selector = f"metadata.name={machine_set_name}"
        for event in self.machineset.watch(namespace=MACHINE_NAMESPACE, field_selector=field_selector, timeout=TIMEOUT):
            requested_replicas = event["object"]["status"]["replicas"]
            ready_replicas = event["object"]["status"]["readyReplicas"]
            if requested_replicas == ready_replicas:
                return True
            else:
                logger.info("Waiting for replicas to match ready replicas")
        return False

    def scale_machine_set(self, machine_set_name: str, replicas: int) -> bool:  # noqa: C901
        """
        Verify that a Machine reflects the desired number of user specified replicas
        :param machine_set_name: (str) name of the machine set
        :param replicas: (int) the number of desired machine replicas
        :return: (bool) True when successfully scaling a Machine set object OR False otherwise
        """

        def _verify_successful_scale_up(machine_set_name: str) -> bool:
            """
            Once a patch operation is successfully completed, a scale up is deemed successful
            if the following conditions are met:
                1. The newly generated machines reach a ready state
                2. New nodes corresponding to the newcly created machines are created
                   and reach a ready state.
            :param machinet_set_name: (str) name of the machine set
            :return: (bool) True if the given machine set is successfully scaled up OR False otherwise.
            """
            scaled_up_machines_list = self.machine.get_machines_in_machineset(machine_set_name)
            creation_phases = {"Provisioning", "Provisioned"}
            new_machine_names = [
                machine.metadata.name
                for machine in scaled_up_machines_list.items
                if machine.status.phase in creation_phases
            ]
            new_machines_ready = True
            for machine_name in new_machine_names:
                new_machines_ready = new_machines_ready and self.machine.is_machine_created(machine_name)
            if new_machines_ready:
                new_nodes_ready = True
                for machine in new_machine_names:
                    logger.debug("Checking that new nodes are available")
                    node_name = self.machine.get_machine_node_ref(machine)
                    new_nodes_ready = new_nodes_ready and self.node.is_node_ready(node_name)
                return new_nodes_ready
            else:
                raise AssertionError("New machine(s) resulting from scaling did not reach a ready state")

        def _verify_successful_scale_down(machine_set_name: str) -> bool:
            """
            Once a patch operation is successfully completed, a scale down is deemed successful
            if the following conditions are met:
                1. Enough machines are deleted to meet the desired number of replicas
                2. Nodes corresponding to the deleted machines are in turn deleted as well.
            :param machinet_set_name: (str) name of the machine set
            :return: (bool) True if the given machine set is successfully scaled down OR False otherwise.
            """
            scaled_down_machines_list = self.machine.get_machines_in_machineset(machine_set_name)
            machine_names_to_be_deleted = [
                machine.metadata.name
                for machine in scaled_down_machines_list.items
                if machine.status.phase == "Deleting"
            ]
            node_names_to_be_deleted = list()
            for machine in machine_names_to_be_deleted:
                node_names_to_be_deleted.append(self.machine.get_machine_node_ref(machine))
            logger.debug(f"Machines to be deleted are: {machine_names_to_be_deleted}")
            excess_machines_deleted = True
            for machine_name in machine_names_to_be_deleted:
                excess_machines_deleted = excess_machines_deleted and self.machine.is_machine_deleted(machine_name)
            if excess_machines_deleted:
                excess_nodes_deleted = True
                for node in node_names_to_be_deleted:
                    logger.debug("Checking that scaled down nodes are removed")
                    excess_nodes_deleted = excess_nodes_deleted and self.node.is_node_deleted(node)
                return excess_nodes_deleted
            else:
                raise AssertionError("Scale down operation did not complete successfully")

        def _is_watched_desired(machine_set_name: str, desired_replicas: str) -> bool:
            """
            After patching a Machine set object with a different replica value, this method
            is meant to verify that the 'replicas' value reflects the value we used with
            the patch operation.
            :param machine_set_name: (str) The name of the machine set
            :param desired_replicas: (int) The number of replicas to be watched
            :return: (bool) True when values match OR False otherwise
            """
            field_selector = f"metadata.name={machine_set_name}"
            for event in self.machineset.watch(
                namespace=MACHINE_NAMESPACE, field_selector=field_selector, timeout=TIMEOUT
            ):
                if event["object"]["status"]["replicas"] == replicas:
                    return True
                else:
                    logger.debug("Waiting for MachineSet to reflect new number of desired replicas")
            return False

        initial_machines = self.machine.get_machines_in_machineset(machine_set_name)
        initial_machine_names = {machine.metadata.name for machine in initial_machines.items}
        initial_machines_count = len(initial_machine_names)
        # If number of existing machine is the same as replicas, nothing to do.
        if initial_machines_count == replicas:
            logger.info("Desired replicas is already equal to number of machines. No sacling required")
            return True
        body = {"spec": {"replicas": replicas}}
        api_response = None
        try:
            api_response = self.machineset.patch(
                name=machine_set_name,
                body=body,
                namespace=MACHINE_NAMESPACE,
                content_type="application/merge-patch+json",
            )
        except ApiException as e:
            logger.error("Exception while updating MachineSet: %s\n", e)
        if not _is_watched_desired(machine_set_name, replicas):
            raise AssertionError("The MachineSet does not reflect the deisred number of replicas")

        if api_response:
            if initial_machines_count < replicas:
                return _verify_successful_scale_up(machine_set_name)
            else:
                return _verify_successful_scale_down(machine_set_name)


class OcpMachines(OcpBase):
    """
    OcpMachineSet class extends OcpBase and encapsulates all methods
    related to managing Openshift Machine Sets.
    :param kube_config_file: A kubernetes config file.
    :return: None
    """

    def __init__(self, kube_config_file=None):
        super().__init__(kube_config_file=kube_config_file)
        self.api_version = "machine.openshift.io/v1beta1"
        self.kind = "Machine"
        self.machine = self.dyn_client.resources.get(api_version=self.api_version, kind=self.kind)

    def get_machines(self) -> ResourceList:
        """
        Get all existing machines
        :return MachineList: A machine list on success OR an empty list on failure
        """
        api_response = list()
        try:
            api_response = self.machine.get(namespace=MACHINE_NAMESPACE)
        except ApiException as e:
            logger.error("Exception while getting all Machines: %s\n", e)
        return api_response

    def get_machine(self, machine_name: str) -> ResourceInstance:
        """
        Get a machine by name
        :param machine_name: (str) Machine name
        :return Machine: A machine resource on success OR None on failure
        """
        api_response = None
        try:
            api_response = self.machine.get(name=machine_name, namespace=MACHINE_NAMESPACE)
        except ApiException as e:
            logger.error("Exception while getting Machine: %s\n", e)
        return api_response

    def get_machines_by_role(self, machine_role: str) -> ResourceList:
        """
        Get existing machines by role
        :param machine_role: (str) The role of the machines to be retrieved
        :return MachineList: A machine list on success Or an empty list on failure
        """
        api_response = list()
        try:
            api_response = self.machine.get(
                namespace=MACHINE_NAMESPACE,
                label_selector="machine.openshift.io/" "cluster-api-machine-role={}".format(machine_role),
            )
        except ApiException as e:
            logger.error("Exception while getting Machine by role: %s\n", e)
        return api_response

    def get_parent_machine_set(self, machine_name: str) -> str:
        """
        Given a machine name, obtains the machine set containing that machine
        :param machine_name: Name of the machine resource
        :return: (str) The name of the machine set containing the machine
        """
        machine = self.get_machine(machine_name)
        machine_role = machine.metadata.labels["machine.openshift.io/cluster-api-machine-role"]
        if "machine.openshift.io/cluster-api-machineset" in machine.metadata.labels.keys():
            return machine.metadata.labels["machine.openshift.io/cluster-api-machineset"]
        else:
            logger.warning(f"machine {machine_name} with role {machine_role} is not part of machineset")
            return ""

    def get_machines_in_machineset(self, machine_set: str) -> ResourceList:
        """
        Get machine resources associated with a machine set
        :param machine_set: The name of the machine set
        :return MachineList: A list of machines associated with the provided machine set
        """
        api_response = None
        try:
            api_response = self.machine.get(
                namespace=MACHINE_NAMESPACE,
                label_selector="machine.openshift.io/" "cluster-api-machineset={}".format(machine_set),
            )
        except ApiException as e:
            logger.error("Exception while getting Machines in a machine set: %s\n", e)
        return api_response

    def get_machine_node_ref(self, machine_name: str) -> str:
        """
        Get the node name associated with a machine
        :param machine_name: (str) The name of the machine for which we want to get the associated node name.
        :return: (str) The name of the node associated with the provided machine name
        """
        field_selector = f"metadata.name={machine_name}"
        for event in self.machine.watch(namespace=MACHINE_NAMESPACE, field_selector=field_selector):
            try:
                node_name = event["object"]["status"]["nodeRef"]["name"]
            except TypeError:
                logger.warning(f"Machine {machine_name} doesn't have a nodeRef field yet ...")
                continue
            else:
                logger.debug(f"Machine ref detected with values: {node_name}")
                return node_name
        logger.error(f"Unable to obtain a nodeRef out of Machine: {machine_name}")
        return None

    def is_machine_created(self, machine_name: str, timeout: int = TIMEOUT) -> bool:
        """
        Method that watches a machine resource reaches a 'Running' state.
        :param machine_name: (str) The name of the machine resource to be watched
        :param tiemout: (int) The amount of time to poll before timing out. Defaults to 300s
        :return: bool. True on success OR False on failure
        """
        field_selector = f"metadata.name={machine_name}"
        for event in self.machine.watch(namespace=MACHINE_NAMESPACE, field_selector=field_selector, timeout=timeout):
            try:
                vm_state = event["object"]["status"]["providerStatus"]["vmState"]
                provider_status_condition = event["object"]["status"]["providerStatus"]["conditions"]
            except TypeError:
                logger.warning(f"Provider Status for machine {machine_name} has not yet been detected ...")
                continue
            else:
                if provider_status_condition[0]["type"] == "MachineCreated":
                    if vm_state == "Running":
                        logger.debug(f"Machine {machine_name} has reached 'Running state'")
                        return True
                    else:
                        logger.debug(
                            "Waiting for Machine to reach 'Running' phase." "Current state is: {}".format(vm_state)
                        )
                        continue
                else:
                    logger.debug("Waiting for new Machine to reach 'MachineCreated' state")
                    continue
        return False

    def is_machine_deleted(self, machine_name: str, timeout: int = TIMEOUT) -> bool:
        """
        Method that verifies successful deletion of a machine resource
        :param machine_name: (str) The name of the machine resource to be watched
        :param timeout: (int) The amount of time to poll before timing out. Defaults to 300s
        :return: bool. True on success OR False on failure
        """
        if self.get_machine(machine_name) is None:
            logger.info("Machine is not present")
            return True
        else:
            logger.debug("Machine seems to be present, let's watch")
            field_selector = f"metadata.name={machine_name}"
            for event in self.machine.watch(field_selector=field_selector, timeout=timeout):
                if self.get_machine(machine_name):
                    logger.debug("machine is still present ...")
                    continue
                else:
                    logger.info("Machine is no longer here")
                    return True
        return False
