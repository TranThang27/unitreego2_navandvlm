# Go2 ROS 2 workspace image: driver + navigation (Nav2/SLAM) + local VLA stack (vlm).
#
# Targets the same distro this project is developed/tested against (see README).
# GPU-backed inference (local Qwen2.5-VL brain, YOLO) needs the NVIDIA Container
# Toolkit on the host and a GPU reservation at `docker run`/`docker compose` time —
# no CUDA base image is required since the pip wheels ship their own CUDA runtime.
#
# NaVILA is intentionally NOT part of this image: it needs its own conda env,
# hand-patched transformers build, and a ~16GB checkpoint pulled at setup time —
# see navila/setup_navila_blackwell.sh and run it on bare metal.
FROM ros:jazzy-ros-base

ENV DEBIAN_FRONTEND=noninteractive

# --- System packages (stable layer, only invalidated by this list changing) ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        gnupg2 \
        lsb-release \
        software-properties-common \
        python3-pip \
        clang \
        portaudio19-dev \
        mesa-utils \
        libgl1-mesa-dev \
        ffmpeg \
        ros-${ROS_DISTRO}-rviz2 \
        ros-${ROS_DISTRO}-rmw-cyclonedds-cpp \
        ros-${ROS_DISTRO}-image-tools \
        ros-${ROS_DISTRO}-vision-msgs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /ros2_ws

# --- Python deps in their own layer: only rebuilt when requirements.txt changes ---
COPY requirements.txt src/requirements.txt
# Ubuntu 24.04 marks the system interpreter "externally managed" (PEP 668); this
# image is disposable so overriding that guard is the pragmatic choice here.
RUN pip install --no-cache-dir --break-system-packages 'numpy<2.0.0' && \
    pip install --no-cache-dir --break-system-packages -r src/requirements.txt

# --- Workspace source + ROS deps + build ---
COPY . src/
RUN . /opt/ros/${ROS_DISTRO}/setup.sh && \
    rosdep update && \
    rosdep install --from-paths src --ignore-src -r -y && \
    colcon build --symlink-install

RUN echo "source /opt/ros/${ROS_DISTRO}/setup.bash" >> /root/.bashrc && \
    echo "source /ros2_ws/install/setup.bash" >> /root/.bashrc && \
    sed --in-place --expression \
        '$isource "/ros2_ws/install/setup.bash"' \
        /ros_entrypoint.sh

# Connection defaults — override at `docker run -e` / compose `environment:`,
# never bake real robot IPs or tokens into the image.
ENV ROBOT_IP=""
ENV ROBOT_TOKEN=""
ENV CONN_TYPE="webrtc"
ENV WEBRTC_SERVER_HOST="0.0.0.0"
ENV WEBRTC_SERVER_PORT="9991"

CMD ["ros2", "launch", "go2_navigation", "bringup.launch.py"]
