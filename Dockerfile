FROM pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DOTSTTS_MODEL=rednote-hilab/dots.tts-mf \
    DOTSTTS_DEVICE=cuda \
    DOTSTTS_PRECISION=bfloat16 \
    DOTSTTS_NUM_STEPS=4 \
    DOTSTTS_GUIDANCE_SCALE=1.2 \
    DOTSTTS_SPEAKER_DIR=/data/speakers \
    DOTSTTS_MODEL_DIR=/data/models \
    WYOMING_URI=tcp://0.0.0.0:10201 \
    HTTP_HOST=0.0.0.0 \
    HTTP_PORT=8180

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt constraints.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt -c constraints.txt

COPY . .
RUN pip install .

RUN mkdir -p /data/models /data/speakers

EXPOSE 10201 8180

CMD ["python", "-m", "dotstts_wyoming", "--uri", "tcp://0.0.0.0:10201", "--speaker-dir", "/data/speakers", "--model-dir", "/data/models", "--http-host", "0.0.0.0", "--http-port", "8180"]
