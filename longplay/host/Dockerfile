#FROM kasmweb/ubuntu-noble-desktop:1.17.0
#ARG USERNAME=kasm-user

FROM lscr.io/linuxserver/webtop:ubuntu-kde
ARG USERNAME=abc
USER root
RUN apt-get update
RUN apt-get install -y \
    libsdl2-dev \
    libsdl2-image-dev \
    libsdl2-ttf-dev \
    libsdl2-mixer-dev \
    zlib1g-dev \
    libavformat-dev \
    libswscale-dev \
    libboost-dev \
    libboost-filesystem-dev \
    libboost-program-options-dev \
    libboost-date-time-dev \
    libboost-iostreams-dev \
    qt6-base-dev \
    qt6-base-dev-tools \
    qt6-tools-dev \
    qt6-tools-dev-tools \
    qt6-l10n-tools \
    qt6-svg-dev \
    libtbb-dev \
    libluajit-5.1-dev \
    liblzma-dev \
    libsqlite3-dev \
    libminizip-dev \
    libsquish-dev \
    libfmt-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY longplay/host/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /home/${USERNAME}/VCMI \
    && mkdir -p /home/${USERNAME}/.local/share/vcmi

RUN echo "${USERNAME} ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

RUN mkdir -p /home/${USERNAME}/VCMI \
             /home/${USERNAME}/.local/share/vcmi/config \
             /home/${USERNAME}/.local/share/vcmi/Mods \
             /home/${USERNAME}/.local/share/vcmi/scripts \
             /home/${USERNAME}/.local/share/vcmi/Saves \
             /home/${USERNAME}/.cache/vcmi \
             /home/${USERNAME}/.config/vcmi

COPY --chown=1000:1000 \
    ./longplay/builder/build/bin/libvcmi.so \
    ./longplay/builder/build/bin/libvcmiclientcommon.a \
    ./longplay/builder/build/bin/libvcmiqt.a \
    ./longplay/builder/build/bin/libvcmiservercommon.a \
    ./longplay/builder/build/bin/vcmiclient \
    ./longplay/builder/build/bin/vcmiserver \
    ./longplay/builder/build/bin/vcmieditor \
    /home/${USERNAME}/VCMI/
RUN chmod +x /home/${USERNAME}/VCMI/vcmiclient
RUN chmod +x /home/${USERNAME}/VCMI/vcmieditor

COPY --chown=1000:1000 ./longplay/host/gamedata/ /home/${USERNAME}/.local/share/vcmi/
COPY --chown=1000:1000 ./config/ /home/${USERNAME}/.local/share/vcmi/config/
COPY --chown=1000:1000 ./Mods/ /home/${USERNAME}/.local/share/vcmi/Mods/
COPY --chown=1000:1000 ./scripts/ /home/${USERNAME}/.local/share/vcmi/scripts/

RUN chown -R 1000:1000 /home/${USERNAME} && \
    chmod -R 777 /home/${USERNAME}

ENV XDG_DATA_HOME=/home/abc/.local/share


COPY ./longplay/host/gamestateservice.py /gamestateservice.py
COPY ./longplay/host/entrypoint.sh /custom-services.d/gamestateservice
RUN chmod +x /custom-services.d/gamestateservice

COPY ./longplay/host/gameservice.sh /custom-services.d/gameservice
RUN chmod +x /custom-services.d/gameservice