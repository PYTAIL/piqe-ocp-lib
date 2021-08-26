# PIQE Test Libraries - PIQE OCP Library

**This is a work in progress and not recommended for consumption at this point.**

The PIQE test libraries are a collection of Python libraries that enable you to interact with OpenShift instances.


## Requirements

* A target OpenShift environment.
* A Kubeconfig file that provides access to the target environment.
* An OpenShift OC client that matches the version of your environment

## Getting started
The following steps will prepare your environment for executing or developing tests.


### Prepare the environment

#### Create virtualenv 

create a virtual environment and activate it.

    python3 -m venv scenario
    source scenario/bin/activate
        
Make sure you have the latest version of pip, wheel, and setuptools

```shell script
python -m pip install --upgrade pip setuptools wheel
```

#### Install the OC client

Download the oc client and extract it into a `bin` directory in the `$PATH`
```shell script
wget https://mirror.openshift.com/pub/openshift-v4/clients/ocp/stable/openshift-client-linux.tar.gz

tar xvzf openshift-client-linux.tar.gz -C ~/bin/
```

#### Setup authentication with OCP cluster

The ocp-lib will use the kubeconfig for authenticating to your cluster. Make sure you have a copy of the `kubeconfig` 
. Once the the file is in place, verify that you can connect to your OpenShift instance.

```shell script
export KUBECONFIG=/<some>/<path>/kubeconfig
$ oc cluster-info
Kubernetes master is running at https://api.<yourdomain>.com:6443
```

### User Guide

Once you're environment is setup per the [prepare the environment](#prepare-the-environment) 
you can install the package. Eventually a Python Package will be available, but for now, install from the repository.

```shell script
pip install git+https://github.com/piqe-test-libraries/piqe-ocp-lib.git
```


### Developer Guide
Once you're environment is setup per the [prepare the environment](#prepare-the-environment) perform the 
following steps


#### Fork Repository

Use the GitHub UI to fork the repository

#### Clone Fork

```shell script
git clone https://github.com/<user>/piqe-ocp-lib.git
```

#### Setup git remote
Setup the original repo as remote repo to be able to continually pull changes

```shell script
cd piqe-ocp-lib
make setup-remote
``` 

#### Setup dev requirements

Run the make file to setup the dev environment. This will install the required dependencies

```shell script
cd piqe-ocp-lib
make dev
```

#### Try running a test

The API library resides under piqe_ocp_lib/api/resources, and the corresponding tests reside under piqe_ocp_lib/tests/resources.

Run the test_ocp_base tests

    pytest -sv piqe_ocp_lib/tests/resources/test_ocp_base.py

Results similar to those shown below should be presented.

    ====================================== test session starts ======================================
    platform linux -- Python 3.7.6, pytest-5.4.1, py-1.8.1, pluggy-0.13.1 -- /vagrant/piqe-test-libraries/piqe-ocp-lib/scenario/bin/python3
    cachedir: .pytest_cache
    OpenShift version: latest
    rootdir: /vagrant/piqe-test-libraries/piqe-ocp-lib
    plugins: dependency-0.5.1, forked-1.1.3, xdist-1.31.0
    collected 1 item

    piqe-ocp-lib/tests/resources/test_ocp_base.py::TestOcpBase::test_init 2020-03-18 16:00:03,318 INFO (get_openshift_cluster_info) openshift tests default configs:
    {'first_master': None}
    2020-03-18 16:00:03,318 INFO (log_start_test_case) Starting test case: test_init
    2020-03-18 16:00:03,883 - [INFO] - piqe_api_logger - test_ocp_base@test_init:25 - The obtained version is: 4.3.0
    PASSED2020-03-18 16:00:03,884 INFO (log_end_test_case) Ending test case: test_init


    ======================================= 1 passed in 0.96s =======================================

#### Create Feature Branch
```shell script
git checkout -b CSSW-<ID>
```

Now you're ready to code and develop on the piqe-ocp-lib!

#### NOTE: Cluster Config

Some task-level APIs or tests require the use of a cluster_config yaml file that describes 
the layout of the cluster and the resources being deployed. You can either specify the file using a command
line flag or set the variable `PIQE_OCP_LIB_CLUSTER_CONF` variable to the path. 

For reference you can refer to the one used in our tests [here](piqe_ocp_lib/tests/config/smoke_ocp_config.yaml)

### Contributions

#### Guidelines
We have the following standards and guidelines

 * All tests must pass
 * All linting must pass

If you forget to run the linting, we have a github actions job that runs through these on any changes. 
This allows us to make sure each patch meets the standards.

We also highly encourage developers to be looking to provide more tests or enhance existing tests for fixes 
or new features they maybe submitting. If there is a reason that the changes don’t have any accompanying tests 
we should be annotating the code changes with `TODO` comments with the following information:

 * State that the code needs tests coverage
 * Quick statement of why it couldn’t be added.
```
#TODO: This needs test coverage. <Reason>.
```
#### Before Submitting

##### Get Latest Changes
Always make sure you have the latest changes from the upstream repo

```shell script
git fetch upstream
git rebase upstream/master
```

##### Check and Fix Linting Errors

```shell script
make lint
# if any failures fix them with the below command
make format
git commit --amend --no-edit
```

##### Squash commits

If you have multiple commits and you've not been using `git commit --amend` then please squash the commits. 
You can use the interactive rebase menu to squash your commits

```shell script
git rebase -i HEAD~<the number of commits to latest developed commit>
```

##### Push to Origin
```shell script
git push origin <branch>
```

##### Create the Pull Request

Use the GitHub UI to create the pull request

When the PR is created it will run the upstream actions that will perform linting checks and initiate downstream tests
that run against a downstream small OCP cluster. 

## Release process

We're maintaining a log of changes for every release. Semantic versioning and Keep a Changelog were chosen as standards. You can find more information about both standards [here](CHANGELOG.md).

This library shall be automatically published to Pypi following the steps below:
1. Update `CHANGELOG.md` with the new changes (Keep a Changelog);
2. Bump your package version with `poetry version major.minor.patch` (Semantic Versioning);
3. Open a PR with these two changes above;
4. Manually create a GitHub release;
5. Successful CI will publish.

### Further improvements

We're currently not running any tests in our CI phase due to some limitations. We should target improving this and remove this burden from developers.
