FROM default-route-openshift-image-registry.apps.artc2023.pc3z.p1.openshiftapps.com/openshift/ubi:latest
LABEL name="openshift-art/art-cd" \
  maintainer="OpenShift Team Automated Release Tooling <aos-team-art@redhat.com>"

# Install build dependencies
WORKDIR /usr/local/src
USER root

# Trust Red Hat IT Root CA
RUN curl -o /etc/pki/ca-trust/source/anchors/RH-IT-Root-CA.crt --fail -L \
         https://password.corp.redhat.com/RH-IT-Root-CA.crt \
 && update-ca-trust extract

RUN curl -o /etc/yum.repos.d/rcm-tools-fedora.repo https://download.devel.redhat.com/rel-eng/RCMTOOLS/rcm-tools-rhel-8-baseos.repo

RUN dnf -y install python38
RUN update-alternatives --set python3 /usr/bin/python3.8
RUN dnf -y install python3-wheel python3-devel gcc krb5-devel wget tar gzip git krb5-workstation rsync python3-rpm koji brewkoji bash-completion vim wget curl iputils procps-ng psmisc net-tools iproute && python3 -m pip install "pip >= 21"

# Install SAST Scanning tools
RUN dnf -y copr enable copr.devel.redhat.com/kdudka/covscan && dnf install -y covscan-client

ARG OC_VERSION=latest
# include oc client
RUN wget -O /tmp/openshift-client-linux-"$OC_VERSION".tar.gz https://mirror.openshift.com/pub/openshift-v4/clients/ocp/"$OC_VERSION"/openshift-client-linux.tar.gz \
  && tar -C /usr/local/bin -xzf  /tmp/openshift-client-linux-"$OC_VERSION".tar.gz oc kubectl \
  && rm /tmp/openshift-client-linux-"$OC_VERSION".tar.gz

COPY art-cd/krb5-redhat.conf /etc/krb5.conf

### Install elliott and doozer
#RUN pip install https://github.com/openshift-eng/doozer/archive/master.zip
#RUN pip install https://github.com/openshift-eng/elliott/archive/master.zip
#
# Set up user
RUN useradd -m -d /home/dev -u 1000 dev
USER 1000
WORKDIR /home/dev