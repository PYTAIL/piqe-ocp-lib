#!/usr/bin/python
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
import random
from random import randint
import sys
import threading
from threading import Lock
import time
from time import sleep

from piqe_ocp_lib import __loggername__
from piqe_ocp_lib.api import ocp_exceptions
from piqe_ocp_lib.api.resources import OcpApps, OcpDeploymentconfigs, OcpEvents, OcpNodes, OcpPods, OcpProjects
from piqe_ocp_lib.api.tasks.populate_cluster.config_schemas import populate_ocp_cluster_config
from piqe_ocp_lib.piqe_api_logger import piqe_api_logger

# logger = logging.getLogger(__loggername__)
logger = piqe_api_logger(__loggername__)


class PopulateOcpCluster:
    cleanup_project_list = []

    def __init__(self, ocp_cluster_config, k8=None):
        self.is_populate_successful = False
        self.total_app_count = 0
        self.ocp_cluster_config = ocp_cluster_config
        # Create objects
        self.project_obj = OcpProjects(kube_config_file=k8)
        self.app_obj = OcpApps(kube_config_file=k8)
        self.dc_obj = OcpDeploymentconfigs(kube_config_file=k8)
        self.pod_obj = OcpPods(kube_config_file=k8)
        self.events_obj = OcpEvents(kube_config_file=k8)
        self.node_obj = OcpNodes(kube_config_file=k8)
        self.ocp_cluster_obj = PopulateOcpCluster.get_ocp_cluster_objects_from_template(self.ocp_cluster_config)
        self.python_version = tuple(sys.version[:5].split(".")[:2])
        self.lock = Lock()

    @staticmethod
    def get_ocp_cluster_objects_from_template(ocp_cluster_config):
        """
        Read the ocp_config.yaml config file and
        use the data to populate the cluster.
        :param ocp_cluster_config: config template to create ocp objects
        :return: ocp_cluster_object
        """
        try:
            return populate_ocp_cluster_config(ocp_cluster_config)
        except Exception as e:
            logger.exception("Failed to create ocp_cluster object: %s", e)
            sys.exit(1)

    def populate_cluster(self, filter="all"):
        """
        filters can be used to select subsets of projects to be deployed
        for any specific run.
        :param filter: A list of strings used to filter which projects
                       to deploy.
        :return: True
        """
        start = time.time()
        if "all" in filter:
            filtered_projects = self.ocp_cluster_obj.projects
        else:
            filtered_projects = [
                p for p in self.ocp_cluster_obj.projects if bool(set(filter) & set(p.project_labels.values()))
            ]
        if not filtered_projects:
            logger.error(
                "None of the filters you provided matched any project labels."
                "Make sure you are entering the values correctly and try"
                "re-running the script."
            )
            raise ocp_exceptions.ConfigError(
                "None of the filters you provided matched any "
                "project labels. Make sure you are entering the values "
                "correctly and try re-running the script."
            )

        else:

            def populate(project):
                logger.info("Starting thread - %s", threading.currentThread().getName())
                current_project = project.project_name
                current_project_labels = project.project_labels
                logger.info("-" * 60)
                logger.info("%s - Current project is: %s", threading.currentThread().getName(), current_project)
                logger.info("-" * 60)

                self.project_obj.create_a_project(current_project, labels_dict=current_project_labels)

                # For every project in the outer loop,
                # loop through the apps to be deployed
                for app in project.apps:
                    with self.lock:
                        self.total_app_count += app.app_count

                    logger.info(
                        "****** %s - Current app template used is: %s",
                        threading.currentThread().getName(),
                        app.app_template,
                    )
                    logger.debug("App Labels : %s", app.app_labels)
                    logger.debug("APP_PARAM : %s", app.app_params)
                    # For every app, deploy the desired count
                    for i in range(app.app_count):
                        logger.info(
                            "----> %s - Now deploying: %s",
                            threading.currentThread().getName(),
                            app.app_template + "-" + str(i),
                        )
                        _, dc_names = self.app_obj.create_app_from_template(
                            current_project, app.app_template, i, app.app_params
                        )

                        if dc_names is None:
                            logger.error(
                                " %s -Failed to deploy template: %s",
                                threading.currentThread().getName(),
                                app.app_template + "-" + str(i),
                            )
                            continue

                        for dc in dc_names:
                            # For every Deployment Config (dc) in an app,
                            # Poll for readiness and list its Pod events
                            dc_available = self.dc_obj.check_dc_status_conditions_availability(
                                current_project, dc, timeout=600
                            )
                            if not dc_available:
                                logger.error(
                                    " %s - Timed out waiting for expected status conditions for " "deploymentconfig %s",
                                    threading.currentThread().getName(),
                                    dc,
                                )
                                sys.exit(1)

                            dc_ready = self.dc_obj.is_dc_ready(current_project, dc, timeout=1200)

                            if dc_ready:
                                # Show any deploymentconfig events
                                dc_events = self.events_obj.list_dc_events_in_a_namespace(current_project, dc)
                                if dc_events:
                                    logger.debug(
                                        "%s - Deploymentconfig events for %s:\n",
                                        threading.currentThread().getName(),
                                        dc,
                                    )
                                    for event in dc_events:
                                        logger.debug(
                                            " %s - \n\tProject: %s\n\tResource: %s\n\tFirstTimestamp: %s"
                                            "\n\tMessage: %s\n"
                                            % (
                                                threading.currentThread().getName(),
                                                event.involvedObject.namespace,
                                                event.involvedObject.name,
                                                event.firstTimestamp,
                                                event.message,
                                            )
                                        )
                                # Show any events from pods associated with this deploymentconfig
                                pod_events = self.events_obj.list_pod_events_in_a_namespace(current_project, dc)
                                if pod_events is not None:
                                    logger.debug("Pod events for %s:\n" % dc)
                                    for event in pod_events:
                                        logger.debug(
                                            "\tProject: %s\n\tResource: %s\n\tFirstTimestamp: %s\n\tMessage: %s\n"
                                            % (
                                                event.involvedObject.namespace,
                                                event.involvedObject.name,
                                                event.firstTimestamp,
                                                event.message,
                                            )
                                        )
                                # Check for currently existing pods associated with this deploymentconfig
                                dc_pod = self.pod_obj.list_pods_in_a_deployment(current_project, dc)
                                if len(dc_pod) == 0:
                                    logger.error(
                                        " %s - No pods for deploymentconfig %s were found in the cluster.",
                                        threading.currentThread().getName(),
                                        dc,
                                    )
                            else:
                                logger.error(
                                    "%s - Timed out waiting for the deploymentconfig %s to become ready."
                                    "Exiting now ...",
                                    threading.currentThread().getName(),
                                    dc,
                                )
                                raise ocp_exceptions.ExecutionError(
                                    "Timed out waiting for the deploymentconfig %s to become ready. Exiting now ..."
                                    % dc
                                )
                            # Update replicas as specified in config file
                            logger.info(
                                "%s - Now updating replicas for app %s", threading.currentThread().getName(), dc
                            )
                            self.dc_obj.update_deployment_replicas(current_project, dc, app.app_replicas)
                            # Label the deployment configs of this app
                            logger.info(
                                "%s - Now labeling deploymentconfig %s", threading.currentThread().getName(), dc
                            )
                            app_labels = app.app_labels
                            self.dc_obj.label_dc(current_project, dc, app_labels)

                    self.is_populate_successful = True

            """
            ThreadPoolExecutor with ContextManager is the recommended way to handle thread in Python3 but it's not
            supported in Python2. Hence we have to use traditional threading module. We have also used threading.Lock()
            class to implement primitive lock objects. Once a thread has acquired a lock, subsequent attempts
            to acquire it block, until it is released.

            For Python2 : We have used threading.Thread to create thread with thread_name and function as args.We will
            loop over all projects from config yaml specified in with --cluster-config option and creates a thread.
            Store all thread in lists and use join() method to complete all threads before it switch to main_thread.

            For Python3 : We have used ThreadPoolExecutor with thread_name_prefix and default process counts. Based on
            python3 doc, default number of thread created by ThreadPoolExecutor will be number processor on server * 5.
            if server has 8 processor, Total number of concurrent thread will be 40. If we have 100 projects, It will
            create 40 thread for first 40 projects and remaining 60 project will be in pool. As any of active thread is
            completed, It will pick next projects from pool. ThreadPoolExecutor with ContextManager will handle all
            threads before switching to main_thread.
            """

            if self.python_version <= ("2", "7"):
                logger.info("Python version is %s", self.python_version)
                threads = list()
                for project in filtered_projects:
                    thread = threading.Thread(target=populate, name=f"Thread_{project.project_name}", args=(project,))
                    threads.append(thread)
                    thread.start()
                for thread in threads:
                    thread.join()
            else:
                logger.info("Python version is %s", self.python_version)
                with ThreadPoolExecutor(thread_name_prefix="Thread") as executor:
                    executor.map(populate, filtered_projects)
                    # result_futures = list(map(lambda x: executor.submit(populate, x), filtered_projects))
                    # results = [f.result() for f in futures.as_completed(result_futures)]

            end = time.time()
            logger.info(
                "Time taken to populate %s projects and %s apps is : %s ",
                len(filtered_projects),
                self.total_app_count,
                round(end - start, 2),
            )

        return self.is_populate_successful

    def longevity(self, duration, scale_replicas=5):
        """
        This method scans all namespaces for deployments labeled 'scalable=True',
        loads them into a list and periodically picks one at random. Once a
        deployment is picked, it will update its replicas to
        random number in the range specified by the args.replicas param.
        The param args.longevity determines the duration of this method.
        :param duration: The duration of the longevity test in seconds.
                         default is 3600.
        :return: boolean True when successful, raise custom exceptions on failure.
        """
        logger.info("*** Starting longevity component. Duration will be: %d seconds ***", duration)
        end = time.time() + duration
        while time.time() < end:
            dc_list = self.dc_obj.list_deployments_in_all_namespaces(label_selector="scalable=True")
            if not dc_list.items:
                logger.error(
                    "No deployments labeled scalable=True were found"
                    "in the cluster. Longevity can only run when"
                    "scalable deployments are present in the cluster."
                    "exiting now ..."
                )
                raise ocp_exceptions.ExecutionError(
                    "No deployments labeled scalable=True were found "
                    "in the cluster. Longevity can only run when "
                    "scalable deployments are present in the cluster."
                    "exiting now ..."
                )
            else:
                bad_dcs = self.dc_obj.find_unhealthy_dcs_in_namespace_list(dc_list.items)
                if bad_dcs:
                    for dc in bad_dcs:
                        current_dc = dc.metadata.name
                        current_namespace = dc.metadata.namespace

                        logger.error(
                            "The DeploymentConfig %s in namespace %s "
                            "is in an invalid state."
                            "See log entries below:",
                            current_dc,
                            current_namespace,
                        )

                        dc_log = self.dc_obj.read_dc_log(current_namespace, current_dc)
                        for line in dc_log:
                            logger.error(line)

                    raise ocp_exceptions.OcpDeploymentConfigInvalidStateError(
                        "Some of the DeploymentConfigs are in invalid state. See log file for more details"
                    )
                else:
                    # # List mem and cpu usage for each node in the cluster # TODO
                    # node_list = node_obj.get_all_nodes().items
                    # # Separator for better log readability
                    # logger.info("="*70)
                    # logger.info("Listing mem and cpu usage for each node in cluster before modifying dc:")
                    # for node in node_list:
                    #     node_name = node.metadata.name
                    #     logger.info("\n\tAllocated resources for node %s :", node_name)
                    #     allocated_resources_list = node_obj.list_node_memory_cpu_usage(node_name)
                    #     for line in allocated_resources_list:
                    #         logger.info("\t%s:", line)

                    # Update replicas
                    rand_dc = random.choice(dc_list.items)
                    rand_dc_name = rand_dc.metadata.name
                    rand_dc_namespace = rand_dc.metadata.namespace
                    updated_replicas = randint(1, scale_replicas)
                    logger.info(
                        "Modifying dc %s in project %s to scale to : %d replicas",
                        rand_dc_name,
                        rand_dc_namespace,
                        updated_replicas,
                    )
                    self.dc_obj.update_deployment_replicas(rand_dc_namespace, rand_dc_name, updated_replicas)
                    # Buffer between replica updates
                    sleep(10)

        return True

    def cleanup(self, filter="all"):
        """ Cleanup projects created by this script """
        if filter == "all":
            filtered_projects = self.ocp_cluster_obj.projects
        else:
            filtered_projects = [
                p for p in self.ocp_cluster_obj.projects if bool(set(filter) & set(p.project_labels.values()))
            ]
        if not filtered_projects:
            logger.error(
                "None of the filters you provided matched any project labels."
                "Make sure you are entering the values correctly and try"
                "re-running the script."
            )
            raise ocp_exceptions.ConfigError(
                "None of the filters you provided matched any project labels."
                "Make sure you are entering the values correctly and try "
                "re-running the script."
            )
        else:
            logger.info("Starting cleanup ... now deleting" " specified projects")
            # TODO : Use watch() instead
            PopulateOcpCluster.cleanup_project_list = filtered_projects[:]
            for project in filtered_projects:
                logger.info("Now deleting Project %s", project.project_name)
                self.project_obj.delete_a_project(project.project_name)
                PopulateOcpCluster.cleanup_project_list.remove(project)
            return PopulateOcpCluster.cleanup_project_list


def argument_parser():
    """
    This script reads a YAML config file that describes the desired OCP layout,
    describing projects and their underlying app. It uses the OcpAppMgmt class to
    deploy and monitor the config.

    This script requires and mandatory argument that provides the path and name
    of the YAML cluster config file.

    Parameters:
      python -m css_openshift/lib/populate_ocp_cluster -h
    usage: populate_ocp_cluster.py [-h] -c CONFIG [-d {INFO,DEBUG,ERROR}]
                               [-l LOGS_DIR] [-m MASTER] [-u USER]
                               [-k8 KUBECONFIG] [-p PASSWORD] [-n LOG_FILE]
                               [-s SPAN] [-r REPLICAS]
                               [-t {populate,longevity,cleanup,all} [{populate,longevity,cleanup,all} ...]]
                               [-f FILTER [FILTER ...]] [--log-to-stdout]

    Process inputs for populate_ocp_cluster

    optional arguments:
      -h, --help            show this help message and exit
      -c CONFIG, --config CONFIG
                            YAML Config file that describes the cluster
      -d {INFO,DEBUG,ERROR}, --debug {INFO,DEBUG,ERROR}
                            The logging debug level. Default is INFO
      -l LOGS_DIR, --log-dir LOGS_DIR
                            log files dir path
      -m MASTER, --master MASTER
                            OCP master node to run against
      -u USER, --user USER  OCP cluster username
      -k8 KUBECONFIG, --kubeconfig KUBECONFIG
                            OCP cluster kubeconfig file path
      -p PASSWORD, --password PASSWORD
                            OCP cluster password
      -n LOG_FILE, --log-file LOG_FILE
                            log file name
      -s SPAN, --span SPAN  The span of the longevity test for scaling apps in
                            seconds
      -r REPLICAS, --replicas REPLICAS
                            The max number of replicas to scale apps in the
                            longevity test
      -t {populate,longevity,cleanup,all} [{populate,longevity,cleanup,all} ...],
        --tests {populate,longevity,cleanup,all} [{populate,longevity,cleanup,all} ...]
                            The specific tests to be run. Valid values
                            are:populate_cluster, longevity, cleanup or all.
      -f FILTER [FILTER ...], --filter FILTER [FILTER ...]
                            A filter to select which projects to deploy.These
                            values need to be passed as space separatedstrings
                            match the ones defined in the config file. Defaults to
                            all.see doc string for an example.
      --log-to-stdout       Log output to stdout as well as file


    Examples:
    Runs all tests with the default duration of one hour
      $ python -m populate_ocp_cluster -c ocp_config.yaml -m ocp_master.lab.com
    Runs the populate test
      $ python -m populate_ocp_cluster --config ocp_config.yaml \
      --master ocp_master.lab.com --tests populate
    Runs the populate test and filtering projects by label
      $ python -m populate_ocp_cluster --config ocp_config.yaml \
      --master ocp_master.lab.com --tests populate --filter label1 label2
    Runs the longevity test for a custom duration of two minutes, then runs cleanup
      $ python -m populate_ocp_cluster --span 120 --config ocp_config.yaml \
      --master dhcp-8-33-141.css.lab.eng.rdu2.redhat.com --tests longevity cleanup
    Run the populate test using module
        pytest -sv css_openshift/tests/unit-tests/test_populate_ocp_cluster.py
    """

    # Define arguments
    parser = argparse.ArgumentParser(description="Process inputs for populate_ocp_cluster")
    if "PIQE_OCP_LIB_CLUSTER_CONF" in os.environ and os.environ["PIQE_OCP_LIB_CLUSTER_CONF"]:
        cfg_path = os.path.abspath(os.path.expandvars(os.path.expanduser(os.environ["PIQE_OCP_LIB_CLUSTER_CONF"])))
        confopt = {"default": cfg_path}
    else:
        confopt = {"required": True}
    parser.add_argument("-c", "--config", action="store", help="YAML Config file that describes the cluster", **confopt)
    parser.add_argument(
        "-d",
        "--debug",
        action="store",
        required=False,
        default="INFO",
        choices=["INFO", "DEBUG", "ERROR"],
        help="The logging debug level. Default is INFO",
    )
    parser.add_argument(
        "-l", "--log-dir", action="store", dest="logs_dir", required=False, default="./logs", help="log files dir path"
    )
    parser.add_argument("-k8", "--kubeconfig", action="store", required=False, help="OCP cluster kubeconfig file path")
    parser.add_argument(
        "-n", "--log-file", action="store", dest="log_file", required=False, default=None, help="log file name"
    )
    parser.add_argument(
        "-s",
        "--span",
        action="store",
        required=False,
        default=3600,
        type=int,
        help="The span of the longevity test for scaling apps " "in seconds",
    )
    parser.add_argument(
        "-r",
        "--replicas",
        action="store",
        required=False,
        default=5,
        type=int,
        help="The max number of replicas to scale apps " "in the longevity test",
    )
    parser.add_argument(
        "-t",
        "--tests",
        nargs="+",
        choices=["populate", "longevity", "cleanup", "all"],
        default="all",
        help="The specific tests to be run. Valid values are:" "populate_cluster, longevity, cleanup or all.",
    )
    parser.add_argument(
        "-f",
        "--filter",
        required=False,
        nargs="+",
        type=str,
        default="all",
        help="A filter to select which projects to deploy."
        "These values need to be passed as space separated"
        "strings match the ones defined "
        "in the config file. Defaults to all."
        "see doc string for an example.",
    )
    parser.add_argument("--log-to-stdout", help="Log output to stdout as well as file", action="store_true")

    return parser


if __name__ == "__main__":
    """
    We always try to populate the cluster using our config file.
    If populating the cluster succeeds, we then run the longevity
    test. When it comes to cleanup, it is set to True by default
    and will only run if both deployment and longevity succeed. If
    a failure occurs we want to preserve the config for
    troubleshooting.
    """

    parser = argument_parser()
    args = parser.parse_args()

    # Read the ocp_config.yaml file , validate the config with defined schema
    # ( populate_ocp_cluster_config class in ocp_config_schemas defines the
    # schema for ocp_config.yaml ) and create 'ocp_cluster_obj'
    # to populate the cluster.
    # try:
    #     ocp_cluster_obj = populate_ocp_cluster_config(args.config)
    # except Exception as e:
    #     logger.exception("Failed to create ocp_cluster object: %s", e)
    #     sys.exit(1)

    # Create an instance of PopulateOcpCluster() class
    populate_cluster = PopulateOcpCluster(args.config, args.kubeconfig)

    populate_cluster.get_ocp_cluster_objects_from_template(args.config)

    if "populate" in args.tests or "all" in args.tests:
        populate_cluster.populate_cluster(args.filter)
    if "longevity" in args.tests or "all" in args.tests:
        populate_cluster.longevity(args.span, scale_replicas=args.replicas)
    if "cleanup" in args.tests or "all" in args.tests:
        populate_cluster.cleanup(args.filter)
