import json
import logging
from time import sleep
from typing import Optional, Union
import warnings

from kubernetes.client.rest import ApiException
from openshift.dynamic.resource import ResourceInstance, ResourceList, Subresource

from piqe_ocp_lib import __loggername__
from piqe_ocp_lib.api.resources import OcpBase

logger = logging.getLogger(__loggername__)


class OperatorhubPackages(OcpBase):
    """
    A class that offers the capability to query and inspect operator package manifests
    Available from the OperatorHub. The Hub provides a catalog of operators from different
    sources.
    :param kube_config_file: A kubernetes config file.
    :return: None
    """

    def __init__(self, kube_config_file=None):
        super().__init__(kube_config_file=kube_config_file)
        self.api_version = "packages.operators.coreos.com/v1"
        self.kind = "PackageManifest"
        self.package_manifest_obj = self.dyn_client.resources.get(api_version=self.api_version, kind=self.kind)

    def get_package_manifest_list(self, catalog: Optional[str] = None) -> Union[ResourceList, list]:
        """
        A method that retrieves the entire list of package manifest objects
        visible by the OperatorHub regardless of the source
        :param catalog: The name of the catalog with which we want to filter results
                        by default, there are three different catalogs available:
                        'certified-operators'
                        'community-operators'
                        'redhat-marketplace'
                        'redhat-operators'
        :return: (ResourceList) a list of PackageManifest objects when successfule, otherwise it
                 returns an empty list.
        TODO: Instead of filtering by catalog, is it better to filter by
              status.catalogSource?
        """
        packages_obj_list = []
        try:
            if not catalog:
                packages_obj_list = self.package_manifest_obj.get()
            else:
                packages_obj_list = self.package_manifest_obj.get(label_selector=f"catalog={catalog}")
        except ApiException as e:
            logger.exception("Exception when calling method get_package_manifest_list: %s\n" % e)
        return packages_obj_list

    def get_package_manifest(self, package_name: str) -> Optional[ResourceInstance]:
        """
        A method that gets the manifest details on a specific operator manifest file
        :param package_name: The name or the operator package manifest object we want
                             to obtain.
        :return: (ResourceInstance) a PackageManifest object if present, otherwise it returns None.
        """
        package_obj = None
        try:
            package_obj = self.package_manifest_obj.get(field_selector=f"metadata.name={package_name}")
        except ApiException as e:
            logger.exception("Exception when calling method get_package_manifest: %s\n" % e)
        if package_obj and len(package_obj.items) == 1:
            return package_obj.items[0]
        elif len(package_obj.items) == 0:
            logger.exception(f"The package {package_name}, could not be detected")
            return None
        else:
            return package_obj.items

    def watch_package_manifest_present(self, package_name: str, timeout: int = 30) -> bool:
        """
        Watch doesn't seem to be supported of resource type PackageManifest
        so we have implement it ourselves.
        :param package_name: (required | str) name of the package to be watched
        :param timeout: (optional | int) maximum time (in seconds) to watch a
                        package before erroring out. Defaults to 30 seconds.
        :return: (bool) True if present, False otherwise
        """
        counter = 0
        while counter < timeout:
            if not self.get_package_manifest(package_name):
                counter += 5
                sleep(5)
                logger.info(f"Waiting for package {package_name} to be available in OperatorHub")
            else:
                logger.info(f"Package {package_name} was detected in OperatorHub")
                return True
        return False

    def get_package_channels_list(self, package_name: str) -> list:
        """
        A method that returns a list of available subscription channels for a particular
        package. Different channels maps to one or more install modes.
        :param package_name: The name of the operator package for which we want to obtain
                             the supported channels list.
        :return: (list) A list of subscription channels.
        """
        if not self.watch_package_manifest_present(package_name):
            logger.error(f"The package {package_name} could not be detected")
        else:
            channels_list = []
            channels_present = False
            while not channels_present:
                try:
                    resp = self.get_package_manifest(package_name=package_name)
                    if resp.status and resp.status.channels:
                        channels_list = resp.status.channels
                        channels_present = True
                except ApiException as e:
                    logger.exception("Exception when calling method get_package_channels_list: %s\n" % e)
        return channels_list

    def get_package_channel_by_name(self, package_name: str, channel_name: str) -> Optional[Subresource]:
        """
        A method that returns a package manifest channel object. Every packagemanifest typically
        has a list of different channels. This method allows the user to get a specific package
        by name.
        : param package_name: (required | str) The name of the packagemanifest.
        : param channel_name: (requires | str) The channel name.
        :return: (Subresource) A channel obj if found, otherwise it returns None.
        """
        channels_list = self.get_package_channels_list(package_name)
        for channel in channels_list:
            if channel.name == channel_name:
                return channel
        logger.error(f"A channel with the name {channel_name} could not be found")
        return None

    def get_channel_suggested_namespace(self, package_name: str, channel_name: str) -> Optional[str]:
        """
        A method that retrieves the suggested namespace for installing an operator. Note not all
        packagemanifests provide this information. In such case, this method will return None.
        :param package_name: (required | str) The name of the packagemanifest.
        :param channel_name: (required | str) The channel name.
        :return: (str) The name of the suggested operator namespace if present, otherwise it returns None.
        """
        channel = self.get_package_channel_by_name(package_name, channel_name)
        if channel and hasattr(channel.currentCSVDesc.annotations, "operatorframework.io/suggested-namespace"):
            return channel.currentCSVDesc.annotations["operatorframework.io/suggested-namespace"]
        else:
            logger.error("No suggested namespace was found for this channel")
        return None

    def get_package_allnamespaces_channels(self, package_name: str) -> list:
        """
        A method that retrieves a list of channels for a packagemanifest
        that allows the user to enable the operator across all namespaces/projects
        of the entire cluster.
        :param package_name: The name of the operator package for which we want to
                             obtain the clusterwide channel name.
        :return: (list) A list of clusterwide channels, if availabele, otherwise
                 the method returns an empty.
        """
        channels_list = self.get_package_channels_list(package_name)
        clusterwide_channels = []
        for channel in channels_list:
            install_modes = channel.currentCSVDesc.installModes
            for im in install_modes:
                if im.type == "AllNamespaces" and im.supported is True:
                    clusterwide_channels.append(channel)
        if len(clusterwide_channels) == 0:
            logger.info(f"No clusterwide channels were found for package: {package_name}")
        return clusterwide_channels

    def get_package_multinamespace_channels(self, package_name: str) -> list:
        """
        A method that retrieves a list of channels for a packagemanifest
        that allows the user to enable the operator in multiple namespaces/projects.
        :param package_name: The name of the operator package for which we want to
                             obtain the multinamespace channel name.
        :return: (list) A list of multinamespace channels, if availabele, otherwise
                 the method returns an empty list.
        """
        channels_list = self.get_package_channels_list(package_name)
        multinamespace_channels = []
        for channel in channels_list:
            install_modes = channel.currentCSVDesc.installModes
            for im in install_modes:
                if im.type == "MultiNamespace" and im.supported is True:
                    multinamespace_channels.append(channel)
        if len(multinamespace_channels) == 0:
            logger.info(f"No MultiNamespace channels were found for package: {package_name}")
        return multinamespace_channels

    def get_package_singlenamespace_channels(self, package_name: str) -> list:
        """
        A method that retrieves a list of channels for a packagemanifest
        that allows the user to enable the operator in a single namespaces/project.
        :param package_name: The name of the operator package for which we want to
                             obtain the single namespace channel name.
        :return: (list) A list of single namespace channel, if availabele, otherwise
                 the method returns an empty list.
        """
        channels_list = self.get_package_channels_list(package_name)
        singlenamespace_channels = []
        for channel in channels_list:
            install_modes = channel.currentCSVDesc.installModes
            for im in install_modes:
                if im.type == "SingleNamespace" and im.supported is True:
                    singlenamespace_channels.append(channel)
        if len(singlenamespace_channels) == 0:
            logger.info(f"No SingleNamespace channels were found for package: {package_name}")
        return singlenamespace_channels

    def get_package_ownnamespace_channels(self, package_name: str) -> list:
        """
        A method that retrieves a list of channels for a packagemanifest
        that allows the user to enable the operator in a single namespaces/project.
        :param package_name: The name of the operator package for which we want to
                             obtain the single namespace channel name.
        :return: (list) A list of single namespace channel, if availabele, otherwise
                 the method returns an empty list.
        """
        channels_list = self.get_package_channels_list(package_name)
        ownnamespace_channels = []
        for channel in channels_list:
            install_modes = channel.currentCSVDesc.installModes
            for im in install_modes:
                if im.type == "OwnNamespace" and im.supported is True:
                    ownnamespace_channels.append(channel)
        if len(ownnamespace_channels) == 0:
            logger.info(f"No OwnNamespace channels were found for package: {package_name}")
        return ownnamespace_channels

    def get_package_default_channel(self, package_name: str) -> Optional[str]:
        """
        A method that returns a packagemanifest's default channel if available
        :param package_name: (required | str) The packagemanifest name
        :return: (str) The defualt channel name, otherwise it returns None.
        """
        package_namnifest = self.get_package_manifest(package_name)
        if not hasattr(package_namnifest.status, "defaultChannel"):
            return None
        else:
            return package_namnifest.status.defaultChannel

    def is_install_mode_supported_by_channel(self, operator_name: str, channel_name: str, install_mode: str) -> bool:
        """
        A method that checks whether a channel supports a given install mode
        :param operator_name: (required | str) The name of the packagemanifest
        :param channel_name: (required | str) The name of the channel
        :param install_mode: (required | str) The install mode we want to check
        :return: (bool) True is supported, False otherwise
        """
        channel_obj = self.get_package_channel_by_name(operator_name, channel_name)
        install_modes_list = channel_obj.currentCSVDesc.installModes
        for im in install_modes_list:
            if im.type == install_mode:
                logger.info(f"The channel {channel_name} 'supported' value is {im.supported}")
                return im.supported

    def get_crd_models_from_manifest(self, package_name, channel_name):
        """
        A method that returns a channel object
        :param package_name: name of the package
        :param channel_name: name of the channel
        :return: list of dictionary alm-examples
        TODO: replace the logic with a method call once CSSWA-526 is merged
        """
        channels_list = self.get_package_channels_list(package_name)
        for channel in channels_list:
            if channel.name == channel_name:
                target_channel = channel
                break
        alm = target_channel.currentCSVDesc.annotations["alm-examples"]
        alm_list = json.loads(alm)
        return alm_list


class OperatorSource(OcpBase):
    """
    A class that provides a user the ability to create OperatorSource objects whcih then can be used
    to create subscriptions to packages available through that source.
    :param kube_config_file: A kubernetes config file.
    :return: None
    """

    warnings.warn(
        "Removed from OpenShift >= 4.6. Deprecated for versions [4.4, 4.5]",
        DeprecationWarning,
    )

    def __init__(self, kube_config_file=None):
        super().__init__(kube_config_file=kube_config_file)
        self.api_version = "operators.coreos.com/v1"
        self.kind = "OperatorSource"
        self.operator_source_obj = self.dyn_client.resources.get(api_version=self.api_version, kind=self.kind)

    def create_operator_source(self, os_name=None, spec_dict=None, body=None, namespace="openshift-marketplace"):
        """
        A method to create a resource of type OperatorSource. This is typically used when an operator
        package manifest is available through some non-standard sources. This allows for the package to be
        accessible from the OperatorHub.
        :param os_name: (required | str) The operator source name
        :param spec_dict: (required | dict) The spec object contains as a minimum five keys:
                          type: The type of registry containing this source, typically appregistry
                          endpoint: The address of the registry, typycally https://quay.io/cnr
                          registryNamespace: The name of the namespace containing the the package in the registry.
                          displayName: The name that will be shown as 'catalog' or 'catalogSource' when added to
                                       the operatorhub.
                          publisher: Name of the publisher of this source.
                          TODO: pass these variables as a combination of required and optional params as opposed
                                to a dictionary to this method?
        :param return: An object of type OperatorSource
        """
        if body:
            os_body = body
        else:
            os_body = {
                "apiVersion": self.api_version,
                "kind": self.kind,
                "metadata": {"name": os_name, "namespace": namespace},
                "spec": spec_dict,
            }
        api_response = None
        try:
            api_response = self.operator_source_obj.create(body=os_body)
        except ApiException as e:
            logger.exception("Exception when calling method create_operator_source: %s\n" % e)
        return api_response

    def get_operator_source(self, os_name, namespace="openshift-marketplace"):
        """
        A method that retrieves an operator source by name from a namespace, which by default,
        will be 'openshift-marketplace'
        :param os_name: (required | str) The name of the operator source to be created
        :param namespace: (optional | str) The name of the namespace where the operator
                           source should be created. Defaults to 'openshift-marketplace'
        :param return: An object of type OperatorSource
        """
        api_response = None
        try:
            api_response = self.operator_source_obj.get(name=os_name, namespace=namespace)
        except ApiException as e:
            logger.exception("Exception when calling method get_operator_source: %s\n" % e)
        return api_response

    def delete_operator_source(self, os_name, namespace="openshift-marketplace"):
        """
        A method to delete an operator source by name in a namespace, which by default, will
        be 'openshift-marketplace'
        :param os_name: (required | str) The name of the operator source to be deleted
        :param namespace: (optional | str) The name of the namespace where the operator
                          source obejec to be deleted resides.
        """
        api_response = None
        try:
            api_response = self.operator_source_obj.delete(name=os_name, namespace=namespace)
        except ApiException as e:
            logger.exception("Exception when calling method create_operator_source: %s\n" % e)
        return api_response


class CatalogSource(OcpBase):
    """
    A class that provides a user the ability to verify the presence of
    CatalogSource objects.
    :param kube_config_file: A kubernetes config file. It overrides
                             the hostname/username/password params
                             if specified.
    :return: None
    """

    def __init__(self, kube_config_file):
        super().__init__(kube_config_file=kube_config_file)
        self.api_version = "operators.coreos.com/v1alpha1"
        self.kind = "CatalogSource"
        self.catalog_source_obj = self.dyn_client.resources.get(api_version=self.api_version, kind=self.kind)

    def create_catalog_source(
        self, cs_name, image, displayName="Optional operators", publisher="Red Hat", namespace="openshift-marketplace"
    ):
        cs_body = {
            "apiVersion": self.api_version,
            "kind": self.kind,
            "metadata": {"name": cs_name, "namespace": namespace},
            "spec": {
                "displayName": displayName,
                "icon": {"base64data": "", "mediatype": ""},
                "image": image,
                "publisher": publisher,
                "sourceType": "grpc",
            },
        }
        api_response = None
        try:
            api_response = self.catalog_source_obj.create(body=cs_body)
        except ApiException as e:
            logger.exception("Exception when calling method create_operator_source: %s\n" % e)
        return api_response

    def delete_catalog_source(self, cs_name, namespace="openshift-marketplace"):
        api_response = None
        try:
            api_response = self.catalog_source_obj.delete(name=cs_name, namespace=namespace)
        except ApiException as e:
            logger.exception("Exception when calling method delete_catalog_source: %s\n" % e)
        return api_response

    def get_catalog_source(self, cs_name: str, namespace: str = "openshift-marketplace") -> Optional[ResourceInstance]:
        """
        A method that retrieves a catalog source by name from a namespace, which by default,
        will be 'openshift-marketplace'
        :param cs_name: (required | str) The name of the catalog source to be retrieved
        :param namespace: (optional | str) The name of the namespace where the catalog
                           source is expected to be. Defaults to 'openshift-marketplace'
        :param return: An object of type CatalogSource
        """
        api_response = None
        try:
            # We can hard code namespace because all catalogsources will go in the
            # openshift-marketplace namespace. NOTE: if that were ever to change,
            # we'll need to parameterize the namespace argument.
            api_response = self.catalog_source_obj.get(name=cs_name, namespace=namespace)
        except ApiException as e:
            logger.exception("Exception when calling method get_catalog_source: %s\n" % e)
        return api_response

    def get_all_catalog_sources(self) -> Optional[ResourceList]:
        """
        A method that retrieves all catalog sources in an openshift cluster.
        :param return: An object of type CatalogSourceList
        """
        api_response = None
        try:
            api_response = self.catalog_source_obj.get()
        except ApiException as e:
            logger.exception("Exception when calling method get_all_catalog_sources: %s\n" % e)
        return api_response

    def is_catalog_source_present(
        self, cs_name: str, namespace: str = "openshift-marketplace", timeout: int = 30
    ) -> bool:
        """
        A method that verifies that a catalog source was created in a namespace. By default it
        will be 'openshift-marketplace'
        :param cs_name: (required | str) The name of the catalog source to be retrieved
        :param namespace: (optional | str) The name of the namespace where the catalog
                           source is expected to be. Defaults to 'openshift-marketplace'
        :param timeout: (optional | int) The amount of time in seconds we expect the watch
                        to be completed.
        :param return: (bool) A boolean value to indicate whether a catalog source is
                       present or not.
        """
        field_selector = f"metadata.name={cs_name}"
        for event in self.catalog_source_obj.watch(namespace=namespace, field_selector=field_selector, timeout=timeout):
            if event["object"] and event["object"]["metadata"]["name"] == cs_name:
                logger.info(f"CatalogSource {cs_name} in namescpace {namespace} was found")
                return True
        logger.warning(
            "CatalogSource {} in namespace {} was not detected within a timeout interval"
            " of {} seconds".format(cs_name, namespace, timeout)
        )
        return False


class Subscription(OcpBase):
    """
    A class that provides a user the ability to create a subscription. A subscription is tied to
    a source, such as a catalogsourceconfig or operatorsource. Creating a subscription automatically
    creates cluster service versions (csv) resources in a targeted set of projects/namespaces where
    they will provide the metadate necessary for creating the custom resource definitions (CRD)
    for creating operator based apps.
    :param kube_config_file: A kubernetes config file.
    :return: None
    """

    def __init__(self, kube_config_file=None):
        super().__init__(kube_config_file=kube_config_file)
        self.api_version = "operators.coreos.com/v1alpha1"
        self.kind = "Subscription"
        self.subscription_obj = self.dyn_client.resources.get(api_version=self.api_version, kind=self.kind)
        self.package_manifest_obj = OperatorhubPackages(kube_config_file=kube_config_file)
        self.catalog_source_obj = CatalogSource(kube_config_file=kube_config_file)

    def create_subscription(self, operator_name: str, channel_name: str, operator_namespace: str) -> ResourceInstance:
        """
        A method to create a subscription object in a namespace. NOTE: the namespace you pick must have an
        OperatorGroup that matches the InstallMode (either AllNamespaces or SingleNamespace modes)
        :param operator_name: (required | str) The name of the operator/package that you want to subscribe to.
        :param channel_name: (required | str) The name of the channel we want to subscribe to.
        :param operator_namespace: (required | str) The namespace where the subscription object will be created.
        :param return: An object of type Subscription
        """
        operator_pkg = self.package_manifest_obj.get_package_manifest(operator_name)
        cs_name = operator_pkg.status.catalogSource
        catalog_source = self.catalog_source_obj.get_catalog_source(cs_name)
        cs_namespace = catalog_source.metadata.namespace
        channel = self.package_manifest_obj.get_package_channel_by_name(operator_name, channel_name)
        csv_name = channel.currentCSV
        # Form the subscription body
        subscription_body = {
            "apiVersion": self.api_version,
            "kind": self.kind,
            "metadata": {"name": operator_name, "namespace": operator_namespace},
            "spec": {
                "channel": channel_name,
                "installPlanApproval": "Automatic",
                "name": operator_name,
                "source": cs_name,
                "sourceNamespace": cs_namespace,
                "startingCSV": csv_name,
            },
        }
        api_response = None
        try:
            api_response = self.subscription_obj.apply(body=subscription_body)
        except ApiException as e:
            logger.exception("Exception when calling method create_subscription: %s\n" % e)
        return api_response

    def get_all_subscriptions(self) -> Optional[ResourceInstance]:
        """
        A method to get all the subscription in the cluster.
        :param return: A Subscription object
        """
        api_response = None
        try:
           api_response = self.subscription_obj.get()
        except ApiException as e:
            logger.exception("Exception when calling method get_all_subscription: %s\n" % e)
        return api_response      


    def get_subscription(self, operator_name: str, namespace: str) -> Optional[ResourceInstance]:
        """
        A method to get a subscription by name from a namespace
        :param operator_name: (required | str) Subscriptions have a one to one mapping to any one
                              operator, so the subscription name is the operator name
        :param namespace: (required | str) The namespace where the subscription is created
        :param return: A Subscription object
        """
        api_response = None
        try:
            api_response = self.subscription_obj.get(name=operator_name, namespace=namespace)
        except ApiException as e:
            logger.exception("Exception when calling method get_subscription: %s\n" % e)
        return api_response

    def delete_subscription(self, operator_name: str, namespace: str) -> ResourceInstance:
        """
        A method to delete a subscription by name from a namespace
        :param operator_name: (required | str) Subscriptions have a one to one mapping to any one
                              operator, so the subscription name is the operator name
        :param namespace: (required | str) The namespace from where the subscription is to be deleted
        :param return: A Subscription object
        """
        try:
            api_response = self.subscription_obj.delete(name=operator_name, namespace=namespace)
        except ApiException as e:
            logger.exception("Exception when calling method delete_subscription: %s\n" % e)
        return api_response

    def watch_subscription_ready(self, operator_name: str, namespace: str, timeout: int = 60) -> bool:
        logger.info("Watching %s subscription for readiness" % operator_name)
        is_operator_ready = False
        field_selector = f"metadata.name={operator_name}"
        for event in self.subscription_obj.watch(namespace=namespace, field_selector=field_selector, timeout=timeout):
            for condition in event["object"]["status"]["conditions"]:
                if condition["message"] == "all available catalogsources are healthy":
                    logger.info("Operator %s installed successfully", operator_name)
                    is_operator_ready = True
                    return is_operator_ready
        logger.error("Operator %s failed", operator_name)
        return is_operator_ready


class OperatorGroup(OcpBase):
    """
    A class that provides a user the ability to create an OperatorGroup. It provides
    multitenant configuration to OLM installed Operators. An OperatorGroup selects a set
    of target namespaces in which to generate required CSV's necessary for deploying
    instances of the CRDs.
    :param kube_config_file: A kubernetes config file.
    :return: None
    """

    def __init__(self, kube_config_file=None):
        super().__init__(kube_config_file=kube_config_file)
        self.api_version = "operators.coreos.com/v1"
        self.kind = "OperatorGroup"
        self.operator_group_obj = self.dyn_client.resources.get(api_version=self.api_version, kind=self.kind)

    def create_operator_group(
        self, og_name: str, namespace: str, target_namespaces: Union[list, str] = []
    ) -> ResourceInstance:
        """
        A method to create an OperatorGroup object. If 'spec' is left out, it means that by default
        this operator group will target all namespaces for deployment. Otherwise, spec will contain
        a key called 'targetNamespaces' which will hold a list of namespaces targeted for deployment.
        NOTE: 'targetNamespaces' has to be consistent with the subscription install mode. Meaning,
        if the subscription install mode is 'SingleNamespace', then 'targetNamespace' in the operator
        group has to be one namespace. In case of a 'AllNamespaces' install mode, then spec in the
        operator group should be left out. Finally, there can be no more than one operator group
        per namespace.
        :param og_name: (required | str) The name of the operator group to be created
        :param namespace: (required | str) The namespace where the operator group
                          is to be created.
        :param target_namespaces: (required | list) When set to '*', it will install clusterwide
                                  otherwise, target namespaces will be a list.
        """
        # Verify that if target_namespaces default is overriden, it is of type list or '*'.
        if not (isinstance(target_namespaces, list) or target_namespaces == "*"):
            err_msg = "'target_namespaces' argument must be provided in either list format or be exactly '*'"
            logger.exception(err_msg)
            raise ValueError(err_msg)
        # TODO: Do further investigation to determine how to use kubernetes models
        # to build the bodies instead of defining them as dictionaries
        og_body = {
            "apiVersion": self.api_version,
            "kind": self.kind,
            "metadata": {"name": og_name, "namespace": namespace},
        }
        # If target_namespaces is not the default [], add it to the body as part of 'spec'
        if target_namespaces == []:
            og_body.update({"spec": {"targetNamespaces": [namespace]}})
        elif target_namespaces != "*":
            og_body.update({"spec": {"targetNamespaces": target_namespaces}})
        try:
            api_response = self.operator_group_obj.apply(body=og_body)
        except ApiException as e:
            logger.exception("Exception when calling method create_operator_group: %s\n" % e)
        return api_response

    def get_operator_group(self, og_name: str, namespace: str) -> Optional[ResourceInstance]:
        """
        A method to get an operator group by name from a namespace
        :param og_name: (requrired | str) The name of the operator group
        :param namespace: (required | str) The name of the namespace containing the
                          operator group
        :param return: An object of type OperatorGroup
        """
        api_response = None
        try:
            api_response = self.operator_group_obj.get(name=og_name, namespace=namespace)
        except ApiException as e:
            logger.exception("Exception when calling method get_operator_group: %s\n" % e)
        return api_response

    def delete_operator_group(self, og_name: str, namespace: str) -> Optional[ResourceInstance]:
        """
        A method to get an operator group by name from a namespace
        :param og_name: (requrired | str) The name of the operator group to be deleted
        :param namespace: (required | str) The name of the namespace containing the
                          operator group to be deleted
        :param return: An object of type OperatorGroup
        """
        api_response = None
        try:
            api_response = self.operator_group_obj.delete(name=og_name, namespace=namespace)
        except ApiException as e:
            logger.exception("Exception when calling method delete_operator_group: %s\n" % e)
        return api_response


class ClusterServiceVersion(OcpBase):
    """
    A class that provides a user the ability to get a ClusterServiceVersion object.
    CSVs get created automatically when a valid subscription object is created. CSV
    is a manifest created from the Operator metadata that assists the Operator
    Lifecycle Manager (OLM) in running the Operator in a cluster. It is the metadata
    that accompanies an operator and contains technical information needed to run
    the Operator.
    :param kube_config_file: A kubernetes config file.
    :return: None
    """

    def __init__(self, kube_config_file=None):
        super().__init__(kube_config_file=kube_config_file)
        self.api_version = "operators.coreos.com/v1alpha1"
        self.kind = "ClusterServiceVersion"
        self.csv_obj = self.dyn_client.resources.get(api_version=self.api_version, kind=self.kind)

    def get_cluster_service_version(self, csv_name: str, namespace: str) -> Optional[ResourceInstance]:
        """
        A method that gets a CSV by name from a namespace.
        :param csv_name: (required | str) The name of the CSV to be obtained. When a CSV is
                         generated after creating a Subscription object, the CSV name can be
                         found in the subscription response object (use get_subscription method
                         in the Subscription class) under status.currentCSV. This typically maps
                         to the channel name that matches the install mode in the package manifest
                         object.
        :param namespace: The name of the namespace containing the CSV
        :param return: A ClusterServiceVersion object
        """
        api_response = None
        try:
            api_response = self.csv_obj.get(name=csv_name, namespace=namespace)
        except ApiException as e:
            logger.exception("Exception when calling method get_cluster_service_version: %s\n" % e)
        return api_response

    def is_cluster_service_version_present(self, csv_name: str, namespace: str, timeout: int = 60) -> bool:
        """
        A method that verifies that a cluster service version was created in a namespace.
        :param cs_name: (required | str) The name of the cluster service version to be retrieved
        :param namespace: (required | str) The name of the namespace where the cluster
                           service version is expected to be.
        :param timeout: (optional | int) The amount of time in seconds we expect the watch
                        to be completed.
        :param return: (bool) A boolean value to indicate whether a catalog source is
                       present or not.
        """
        field_selector = f"metadata.name={csv_name}"
        for event in self.csv_obj.watch(namespace=namespace, field_selector=field_selector, timeout=timeout):
            if event["object"] and event["object"]["metadata"]["name"] == csv_name:
                logger.info(f"ClusterServiceVersion {csv_name} in namespace {namespace} was found")
                return True
        logger.warning(
            "ClusterServiceVersion {} in namespace {} was not detected within a timeout interval"
            " of {} seconds".format(csv_name, namespace, timeout)
        )
        return False

    def delete_cluster_service_version(self, csv_name: str, namespace: str) -> bool:
        """
        A method to delete an existing CSV.
        :param csv_name: (required | str) The CSV name
        :param namespace: (required | str) The namespace where the CSV resides
        :return: A cluter service version object or None
        """
        api_response = None
        try:
            api_response = self.csv_obj.delete(name=csv_name, namespace=namespace)
        except ApiException as e:
            logger.error(f"Failed to delete CSV due to: {e}")
        return api_response
