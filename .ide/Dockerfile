# CNB 云原生开发沙箱镜像（lunar-lab）
# 铁律：构建上下文只有本文件 → 禁止任何 COPY；依赖全部写死在 RUN 里。
# 版本与仓库 requirements.txt 对齐（本机实测通过的组合：Python 3.12 / mujoco 3.17.0）。
FROM cnbcool/default-dev-env:latest

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# ── 系统层：离屏渲染（MuJoCo osmesa）+ 常用工具 ───────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        libosmesa6 libgl1 libegl1 libegl-mesa0 libglew2.2 \
        libglib2.0-0 libsm6 libxrender1 libxext6 \
        git curl ca-certificates build-essential python3-venv \
    && rm -rf /var/lib/apt/lists/*

# ── Python 层：与 requirements.txt 完全一致的锁定版本 ──────────────────────────
RUN python3 -m pip install --no-cache-dir --upgrade pip \
    && python3 -m pip install --no-cache-dir \
        mujoco==3.17.0 \
        numpy==2.5.4 \
        trimesh==5.2.0 \
        coacd==1.0.14 \
        manifold3d==3.5.4 \
        pillow==13.0.0 \
        pyyaml==6.0.2

# ── 渲染自检：镜像若回退到 docker.image，这条会在 stage 1 立即暴露 ─────────────
RUN python3 -c "import mujoco, numpy, trimesh; print('deps', mujoco.__version__, numpy.__version__, trimesh.__version__)" \
    && MUJOCO_GL=osmesa python3 -c "import mujoco; m=mujoco.MjModel.from_xml_string('<mujoco><worldbody><geom size=\".1\"/></worldbody></mujoco>'); print('mujoco model ok', m.ngeom)"

WORKDIR /workspace
