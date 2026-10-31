# CNB 云原生开发沙箱镜像（lunar-lab R1）
# 铁律：构建上下文只有本文件 → 禁止 COPY；依赖全部写死在 RUN 里。
# 由于基础镜像的系统 Python 受 PEP 668 保护，依赖装进 /opt/lunar 独立 venv 并置于 PATH 前。
FROM cnbcool/default-dev-env:latest

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        libosmesa6 libgl1 libegl1 libegl-mesa0 libglew2.2 \
        libglib2.0-0 libsm6 libxrender1 libxext6 \
        git curl ca-certificates build-essential python3-venv \
    && rm -rf /var/lib/apt/lists/*

# 独立 venv：绕开 externally-managed-environment，且不污染系统 Python
RUN python3 -m venv /opt/lunar \
    && /opt/lunar/bin/python -m pip install --no-cache-dir --upgrade pip \
    && /opt/lunar/bin/python -m pip install --no-cache-dir \
        mujoco==3.17.0 \
        numpy==2.5.4 \
        trimesh==5.2.0 \
        coacd==1.0.14 \
        manifold3d==3.5.4 \
        pillow==13.0.0 \
        pyyaml==6.0.2 \
        rtree==1.4.1 \
        networkx==3.7
ENV PATH=/opt/lunar/bin:$PATH \
    VIRTUAL_ENV=/opt/lunar

# 自检：镜像若回退到 docker.image，这里会立刻暴露
RUN python3 -c "import mujoco, numpy, trimesh; print('deps', mujoco.__version__, numpy.__version__, trimesh.__version__)" \
    && MUJOCO_GL=osmesa python3 -c "import mujoco; mujoco.MjModel.from_xml_string('<mujoco><worldbody><geom size=\".1\"/></worldbody></mujoco>'); print('mujoco model ok')" \
    && python3 -c "import sys; print('python', sys.executable)"

WORKDIR /workspace
