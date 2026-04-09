FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
SHELL ["/bin/bash", "-lc"]

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg2 \
    lsb-release \
    ca-certificates \
    software-properties-common \
    python3 \
    python3-pip \
    python3-venv \
    python3-numpy \
    python3-opencv \
    python3-h5py \
    git \
    x11-apps \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --no-cache-dir --break-system-packages colcon-common-extensions

RUN curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key | gpg --dearmor -o /usr/share/keyrings/ros-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" \
      > /etc/apt/sources.list.d/ros2.list

RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-jazzy-ros-base \
    ros-jazzy-rmw-cyclonedds-cpp \
        ros-jazzy-metavision-driver \
    ros-jazzy-event-camera-codecs \
    ros-jazzy-event-camera-msgs \
    ros-jazzy-event-camera-renderer \
        ros-jazzy-spinnaker-camera-driver \
        ros-jazzy-spinnaker-synchronized-camera-driver \
        ros-jazzy-flir-camera-msgs \
        ros-jazzy-flir-camera-description \
    ros-jazzy-cv-bridge \
    ros-jazzy-rosbag2-storage-mcap \
    ros-jazzy-rosbag2-py \
    ros-jazzy-sensor-msgs \
    ros-jazzy-image-tools \
        ros-jazzy-rqt-image-view \
        python3-rosdep \
        python3-vcstool \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

RUN mkdir -p /opt/basler_ws/src && \
        git clone --depth 1 --branch jazzy https://github.com/basler/pylon-ros-camera.git /opt/basler_ws/src/pylon_ros2_camera

COPY installers/basler /tmp/basler_installers
COPY docker/patch_basler_no_blaze.sh /usr/local/bin/patch_basler_no_blaze.sh
COPY docker/setup_basler_pylon.sh /usr/local/bin/setup_basler_pylon.sh
RUN chmod +x /usr/local/bin/patch_basler_no_blaze.sh /usr/local/bin/setup_basler_pylon.sh

RUN if compgen -G "/tmp/basler_installers/*.deb" > /dev/null; then \
            apt-get update && \
            apt-get install -y --no-install-recommends /tmp/basler_installers/*.deb || \
                (apt-get -f install -y && apt-get install -y --no-install-recommends /tmp/basler_installers/*.deb); \
            rm -rf /var/lib/apt/lists/*; \
        else \
            echo "No Basler SDK installers present at build time; Basler driver can be built later inside the container."; \
        fi

RUN source /opt/ros/jazzy/setup.bash && \
        rosdep init 2>/dev/null || true && \
        rosdep update || true

RUN source /opt/ros/jazzy/setup.bash && \
        apt-get update && \
        cd /opt/basler_ws && \
        rosdep install --from-paths src --ignore-src -r -y || true

RUN source /opt/ros/jazzy/setup.bash && \
        if [ -f /opt/pylon/include/pylon/PylonIncludes.h ]; then \
            if [ ! -f /opt/pylon/include/pylon/BlazeInstantCamera.h ]; then \
                /usr/local/bin/patch_basler_no_blaze.sh /opt/basler_ws/src/pylon_ros2_camera; \
            fi; \
            cd /opt/basler_ws && colcon build --symlink-install; \
        else \
            echo "Basler pylon SDK not detected at build time; install it later with setup_basler_pylon.sh."; \
        fi

COPY pyproject.toml /workspace/pyproject.toml
COPY src /workspace/src
RUN python3 -m pip install --no-cache-dir --break-system-packages --no-deps -e /workspace

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["sleep", "infinity"]
