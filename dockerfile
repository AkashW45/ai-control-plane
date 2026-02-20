FROM rundeck/rundeck:5.3.0

USER root

RUN apt-get update && \
    apt-get install -y git maven curl && \
    apt-get clean

USER rundeck
