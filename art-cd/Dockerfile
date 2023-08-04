FROM registry.redhat.io/ubi8/ubi:latest
LABEL name="openshift-art/art-cd" \
  maintainer="OpenShift Team Automated Release Tooling <aos-team-art@redhat.com>"

# Install build dependencies
WORKDIR /usr/local/src
USER root
RUN dnf -y install python38
RUN update-alternatives --set python3 /usr/bin/python3.8
RUN dnf -y install python3-wheel python3-devel gcc krb5-devel wget tar gzip git krb5-workstation rsync python3-rpm \
    && python3 -m pip install "pip >= 21"

ARG OC_VERSION=latest
# include oc client
RUN wget -O /tmp/openshift-client-linux-"$OC_VERSION".tar.gz https://mirror.openshift.com/pub/openshift-v4/clients/ocp/"$OC_VERSION"/openshift-client-linux.tar.gz \
  && tar -C /usr/local/bin -xzf  /tmp/openshift-client-linux-"$OC_VERSION".tar.gz oc kubectl \
  && rm /tmp/openshift-client-linux-"$OC_VERSION".tar.gz


# Trust Red Hat IT Root CA
RUN curl -o /etc/pki/ca-trust/source/anchors/RH-IT-Root-CA.crt --fail -L \
         https://password.corp.redhat.com/RH-IT-Root-CA.crt \
 && update-ca-trust extract


# Install runtime dependencies
COPY images/artcd/files/ /

### Install elliott and doozer
#RUN pip install https://github.com/openshift-eng/doozer/archive/master.zip
#RUN pip install https://github.com/openshift-eng/elliott/archive/master.zip
#
# Set up user
RUN useradd -m -d /home/dev -u 1000 dev
USER 1000
WORKDIR /home/dev