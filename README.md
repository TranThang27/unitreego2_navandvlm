# Unitree Go2 — ROS 2 Navigation & Vision-Language-Action

A ROS 2 workspace for the Unitree Go2 quadruped that pairs a classic navigation
stack (SLAM Toolbox mapping + Nav2) with a **Vision-Language-Action (VLA)** layer:
the robot can be driven by typing a natural-language instruction instead of a
joystick or a Nav2 goal. Two interchangeable VLA brains are included — a local
**Qwen2.5-VL** reasoning loop and **NaVILA** (VILA-8B), a model purpose-trained
for language-guided navigation.

|Systems|ROS2 distro|Build status|
|--|--|--|
|Ubuntu 24.04|jazzy|![ROS2 CI](https://github.com/abizovnuralem/go2_ros2_sdk/actions/workflows/ros_build.yaml/badge.svg)|

This project is derived from [abizovnuralem/go2_ros2_sdk](https://github.com/abizovnuralem/go2_ros2_sdk)
(the community `go2_robot_sdk` WebRTC driver) and extends it with:

- **A cleaner point-cloud pipeline for SLAM/Nav2.** `go2_navigation`'s C++
  `lidar_processor_cpp` nodes run Statistical Outlier Removal + Radius Outlier
  Removal on top of the driver's own voxel-deduplicated scan, all parameterized
  per-node (see [`go2_navigation/src`](go2_navigation/src)) — noticeably less
  speckle noise feeding into `slam_toolbox`/`AMCL` than an unfiltered aggregated
  cloud.
- **A steadier driver loop.** Robot data (WebRTC/lidar decode) is processed on
  its own thread instead of blocking the asyncio event loop, and lidar
  decoding is done as bulk buffer copies rather than a per-point Python loop —
  both matter for keeping `/camera/image_raw` and `/scan` rates stable while a
  VLA brain is polling frames every step.
- **Config-driven robot connection.** Robot IP/token/transport live in
  [`go2_navigation/config/robot.yaml`](go2_navigation/config/robot.yaml) instead
  of being hardcoded, with env vars (`ROBOT_IP`/`ROBOT_TOKEN`/`CONN_TYPE`) still
  free to override per-run.
- **One arbitration point for motion commands.** `twist_mux` merges teleop/VLA
  output (`/cmd_vel_joy`, priority 10) and Nav2 (`/cmd_vel`, priority 5), so the
  navigation stack and the VLA stack never fight over the drivetrain.
- **A full VLA layer on top**, entirely new relative to upstream: two
  swappable brains (local Qwen2.5-VL or NaVILA) behind the same safety-closed
  loop (`/odom` + `/scan` + E-Stop) — see below.

## Architecture

```
                         ┌────────────────────────────┐
                         │     Unitree Go2 hardware    │
                         └──────────────┬───────────────┘
                                        │ WebRTC (LAN)
                         ┌──────────────▼───────────────┐
                         │      go2_robot_sdk driver      │  camera · odom · IMU · lidar
                         └───────┬────────────────┬──────┘
                     /camera/image_raw      /odom, /scan
                                 │                │
              ┌──────────────────┘                └──────────────────┐
              ▼                                                      ▼
   ┌────────────────────────┐                          ┌───────────────────────────┐
   │   Nav2 + slam_toolbox   │  mapping/navigation       │        VLA brain          │
   │      (go2_navigation)   │  launch.py · filtered      │  Qwen2.5-VL  or  NaVILA   │
   │  SOR/ROR pointcloud     │  pointcloud (SOR + ROR)   │  (System-2: text action)  │
   └────────────┬────────────┘                          └─────────────┬─────────────┘
                │ /cmd_vel                          /cmd_vel_joy (MotionController,
                │                                    System-1: odom/lidar closed loop)
                └───────────────────┬─────────────────────────────────┘
                                    ▼
                            ┌───────────────┐
                            │   twist_mux   │  joy/VLA (prio 10) > Nav2 (prio 5)
                            └───────┬───────┘
                                    ▼
                        go2_robot_sdk driver → Go2 built-in gait
```

## Repository map

| Path | Role |
|---|---|
| [`go2_robot_sdk/`](go2_robot_sdk) | WebRTC/LAN driver — camera, odom, lidar, URDF |
| [`go2_navigation/`](go2_navigation) | Bringup, mapping, Nav2, C++ lidar filtering pipeline |
| [`go2_control/`](go2_control) | Keyboard teleop node |
| [`go2_interfaces/`](go2_interfaces) | Shared ROS 2 message definitions |
| [`vlm/`](vlm) | Local VLA stack: Qwen2.5-VL engine, YOLO-assisted servoing, web console |
| [`navila/`](navila) | NaVILA (VILA-8B) inference server + setup/eval tooling (bare metal, not containerized) |
| [`docker/`](docker) | Containerized driver + navigation + local VLA bringup |

## Requirements & installation

```shell
mkdir -p ros2_ws
cd ros2_ws
git clone --recurse-submodules https://github.com/TranThang27/unitreego2_navandvlm.git src
sudo apt install ros-$ROS_DISTRO-image-tools ros-$ROS_DISTRO-vision-msgs
sudo apt install python3-pip clang portaudio19-dev
cd src
pip install -r requirements.txt
cd ..
```
Watch for errors from `pip install` — some optional features silently degrade if it
doesn't complete cleanly (e.g. `open3d` doesn't yet support `python3.12`; use a
`python3.11` venv for that dependency if needed).

Build the workspace (`ros2`/`rosdep` required — see the
[ROS 2 install guide](https://docs.ros.org/en/jazzy/Installation.html)):
```shell
source /opt/ros/$ROS_DISTRO/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build
```

## Docker

```shell
cd docker
cp .env.example .env    # if you keep one locally; otherwise export ROBOT_IP inline
ROBOT_IP=<go2-lan-ip> docker compose up go2                 # driver + Nav2 stack
ROBOT_IP=<go2-lan-ip> docker compose --profile vla up vlm   # + local VLA web console (GPU)
```
The image builds on `ros:jazzy-ros-base`, matching the distro this project is
developed against. `network_mode: host` is required for ROS 2 DDS discovery and
for the driver's WebRTC session with the robot on the LAN. The `vlm` service
requests a GPU via the [NVIDIA Container Toolkit](https://github.com/NVIDIA/nvidia-container-toolkit) —
install that on the host first. **NaVILA is not containerized**: it needs its
own conda environment, a hand-patched `transformers` build for Blackwell GPUs,
and a ~16 GB checkpoint pulled at setup time, so it's run on bare metal via
[`navila/setup_navila_blackwell.sh`](navila/setup_navila_blackwell.sh) — see the
[NaVILA section](#brain-2--navila-vila-8b) below.

Never bake a real `ROBOT_IP`/`ROBOT_TOKEN` into the image or into
`go2_navigation/config/robot.yaml` — pass them as environment variables at run
time instead.

## Usage

Put the Go2 in Wi-Fi/STA mode and note its LAN IP (mobile app → Device → Data →
Automatic Machine Inspection → STA Network: `wlan0`). Set it once in
[`go2_navigation/config/robot.yaml`](go2_navigation/config/robot.yaml) or pass
`ROBOT_IP=<ip>` on any launch command (env always wins).

```shell
source install/setup.bash
```

### Mapping

```shell
ros2 launch go2_navigation mapping.launch.py
```
Mark a dock rectangle with tape as a fixed starting point. In the SlamToolbox
panel in `rviz`, select **Start At Dock**, drive the robot around with a
controller to build the map, then **Save Map** / **Serialize Map**.

### Autonomous navigation (Nav2)

```shell
ros2 launch go2_navigation navigation.launch.py
```
Loads a saved map and drives the robot with Nav2's standard global/local
planner stack + AMCL localization — set goals from `rviz` as usual.

### Manual teleop

```shell
ros2 run go2_control keyboard_teleop
```
Arrows = move, `q`/`e` = rotate, space = stop, `x` = quit. Releasing all keys
for >0.4 s triggers a dead-man stop.

## VLA navigation

Instead of a Nav2 goal, type an instruction and let a vision-language model
decide the motion step by step from the live camera feed. **No RL or learned
locomotion is involved anywhere in this stack** — every brain below only ever
emits a discrete motion command (`move forward 25 cm`, `turn left 30°`,
`stop`); the Go2's own built-in gait and this repo's closed-loop
`MotionController` (odom + lidar + E-Stop) execute it.

### Brain 1 — local Qwen2.5-VL (`vlm` package, "Demo1")

```shell
ros2 launch go2_navigation bringup.launch.py teleop:=true
```
```shell
cd ros2_ws/src
./vlm/scripts/run_demo1.sh
```
Open `http://localhost:8001`, type a goal in natural language (e.g. *"go to
the water bottle, turn right, stop at the chair"*) or a manual command (`move
forward 75 cm`, `turn left 90 deg`). Each step: camera frame → Qwen2.5-VL
prompt (with live odom/lidar/bbox metrics injected as state) → JSON
`{action, value, unit, is_finished, ...}` → `MotionController` executes →
repeat until `is_finished` or **Stop/E-Stop**.

Two control modes (`VLA_CONTROL`):
- `vlm` (default) — the model reasons over injected state and returns the next action.
- `servo` — continuous closed-loop visual servoing driven by YOLO detections,
  bypassing the LLM once a target is locked on.

Swap in a stronger model instead of the local 3B:
```shell
VLA_BRAIN=api VLA_API_URL=<endpoint> VLA_API_KEY=<key> VLA_MODEL=qwen2.5-vl-7b-instruct \
  ./vlm/scripts/run_demo1.sh
```

<details>
<summary>Configuration reference — local VLM brain</summary>

| Env | Default | Meaning |
|---|---|---|
| `VLA_BRAIN` | `local` | `local` (Qwen2.5-VL-3B) \| `api` (OpenAI-compatible endpoint) \| `navila` |
| `VLA_CONTROL` | `servo` | `servo` (visual servo, YOLO-driven) \| `vlm` (JSON reasoning loop) |
| `USE_YOLO` | `1` | `0` disables the YOLO detector |
| `VLA_MAX_STEPS` | `20` | max steps per instruction |
| `VLA_MAX_TURN_DEG` | `10` | hard cap on turn angle per step (all brains) |
| `VLA_SEARCH_MAX_DEG` | `360` | give up searching after this much cumulative scan rotation |
| `VLA_HFOV_DEG` | `90` | camera horizontal FOV, used to convert pixel offset → angle |
| `VLA_CENTER_TOL_DEG` | `5` | (servo) angular tolerance considered "centered" |
| `VLA_SERVO_HZ` / `VLA_SERVO_VX` / `VLA_SERVO_WZ_MAX` / `VLA_SERVO_KP` | `20` / `0.25` / `0.175` / `1.5` | servo loop rate, forward speed, max turn rate, turn gain |
| `VLA_STOP_BOTTOM_PX` | `20` | stop once the target bbox bottom is within this many px of the frame edge |
| `MOTION_LIN_SPEED` / `MOTION_ANG_SPEED` / `MOTION_ANG_MAX_DEG` | `0.3` / `0.35` / `10` | discrete move/turn command speeds and turn-rate ceiling |
| `MOTION_FRONT_STOP` | `0.30` | lidar obstacle distance (m) that halts forward motion |
| `MOTION_TURN_SIGN` | `1` | set to `-1` if the robot turns opposite to the commanded direction |
| `VLA_YOLO_WEIGHTS` / `VLA_YOLO_MIN_CONF` / `VLA_YOLO_IMGSZ` | `yolo11n.pt` / `0.3` / `960` | detector weights, confidence threshold, inference resolution |
| `VLA_LOG_DIR` | `vla_logs` | per-step JSONL log directory |
| `DEMO_MOCK` / `VLM_SKIP_MODEL` | — | run the UI without a robot / without loading the model |

Full source of truth for these lives in [`vlm/webconsole/demo1/navloop.py`](vlm/webconsole/demo1/navloop.py)
and [`vlm/webconsole/demo1/motion.py`](vlm/webconsole/demo1/motion.py).
</details>

### Brain 2 — NaVILA (VILA-8B)

[NaVILA](https://github.com/AnjieCheng/NaVILA) is an 8B vision-language-action
model trained specifically for language-guided navigation. It's integrated as a
**System-2 / System-1 split brain**:

```
camera → 8-frame sliding buffer → HTTP → NaVILA (VILA-8B, System-2, GPU)
      → mid-level action text → parser → MotionCmd
      → MotionController → twist_mux → go2_driver → Go2 built-in gait (System-1)
```

- **System-2** (`navila_server.py`, its own conda env, port `8100`) loads the
  8B checkpoint once and turns 8 camera frames + the instruction into an
  action sentence (`"The next action is move forward 25 cm."`) — a pure
  action policy, no chain-of-thought.
- **System-1** is the same odom/lidar-closed-loop `MotionController` used
  above; NaVILA never touches locomotion or gait, only high-level intent.

First-time setup (downloads the code repo + checkpoint, patches `transformers`
for Blackwell GPUs):
```shell
bash navila/setup_navila_blackwell.sh
```

One-command run (driver + NaVILA server + web console):
```shell
cd ros2_ws/src/navila
./scripts/run.sh
```
Open `http://localhost:8001` and type an instruction **in English** (NaVILA is
trained on English R2R-style instructions), e.g. *"Walk forward down the
hallway and stop near the chair."* The reasoning panel shows the raw NaVILA
output, per-token confidence, and a link to the exact 8 frames the model
received.

<details>
<summary>Configuration reference — NaVILA brain</summary>

| Env / arg | Default | Meaning |
|---|---|---|
| `VLA_BRAIN=navila` | — | routes control to the NaVILA server |
| `VLA_NAVILA_URL` | `http://127.0.0.1:8100` | NaVILA server address |
| `VLA_NAVILA_FRAMES` | `8` | frames sent per request (must match server `--num-frames`) |
| `VLA_NAVILA_HISTORY_MAX` | `64` | raw history frames kept per instruction; uniformly resampled down to `VLA_NAVILA_FRAMES`, always including the first and current frame (matches the paper's sampling scheme) |
| `NAVILA_FALLBACK` | `stop` | behavior when the model output fails to parse: `stop` \| `scan` |
| `NAVILA_PREPROC` | `pad` | frame preprocessing: `fov` (undistort + forward crop, closest to training distribution) \| `pad` (full fisheye) \| `resize` \| `crop` |
| server `--model-path` | — | path to the downloaded checkpoint |
| server `--port` | `8100` | HTTP port |
| server `--num-frames` | `8` | frames processed per request |

Full parameter tables, the three Blackwell inference fixes (8-bit + eager
attention + 4D causal mask — see [`navila/setup_navila_blackwell.sh`](navila/setup_navila_blackwell.sh)),
and eval/debug tooling (`navila/tools/`) are documented inline in that script
and in [`navila/scripts/`](navila/scripts).
</details>

## Acknowledgements & citations

- Built on [abizovnuralem/go2_ros2_sdk](https://github.com/abizovnuralem/go2_ros2_sdk)
  (RoboVerse community) — see [`LICENSE`](LICENSE).
- **NaVILA** — An-Chieh Cheng et al., *"NaVILA: Legged Robot Vision-Language-Action
  Model for Navigation"*, 2024. Code: [AnjieCheng/NaVILA](https://github.com/AnjieCheng/NaVILA),
  checkpoint: `a8cheng/navila-llama3-8b-8f` on Hugging Face. See the official
  repository for the paper and up-to-date citation.
- **Qwen2.5-VL** — Alibaba Qwen team, model `Qwen/Qwen2.5-VL-3B-Instruct`.
- **Ultralytics YOLO11** — [ultralytics/ultralytics](https://github.com/ultralytics/ultralytics).
- **Nav2** and **slam_toolbox** — the ROS 2 Navigation Working Group /
  [ros-navigation](https://github.com/ros-navigation) and
  [SteveMacenski/slam_toolbox](https://github.com/SteveMacenski/slam_toolbox).
- **Point Cloud Library (PCL)** — used for the SOR/ROR filtering pipeline in `go2_navigation`.
- **twist_mux** — [ros-teleop/twist_mux](https://github.com/ros-teleop/twist_mux),
  used to arbitrate teleop/VLA vs. Nav2 velocity commands.
- **aiortc** — vendored WebRTC implementation used by the Go2 driver.

## License

BSD 2-Clause — see [`LICENSE`](LICENSE). Note: some vendored/derived source
files under `go2_navigation/` carry a BSD-3-Clause header inherited from
upstream; if you plan to redistribute, reconcile this with project counsel
before publishing rather than assuming one license governs the whole tree.
