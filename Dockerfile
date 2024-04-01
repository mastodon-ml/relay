FROM python:3.12-alpine

# add env var to let the relay know it's in a container
ENV DOCKER_RUNNING=true

# setup various container properties
VOLUME ["/data"]
CMD ["python3", "-m", "relay"]
EXPOSE 8080/tcp
WORKDIR /opt/activityrelay

# only copy necessary files
COPY relay ./relay
COPY pyproject.toml ./

# install and update important python modules
RUN pip3 install -U setuptools wheel pip

# install relay deps
RUN pip3 install `python3 -c "import tomllib; print(' '.join(dep.replace(' ', '') for dep in tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))"`
