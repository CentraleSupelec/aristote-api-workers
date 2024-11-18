FROM python:3.10
LABEL maintainer="contact@illuin.tech"

RUN apt-get update -y && apt-get upgrade -y

RUN pip install --no-cache-dir torch==2.0.1 --index-url https://download.pytorch.org/whl/cpu

WORKDIR /server_app/

RUN ln -snf /usr/share/zoneinfo/Europe/Paris /etc/localtime && echo Europe/Paris > /etc/timezone

RUN python -m pip install --upgrade pip

COPY ./requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

RUN python -m nltk.downloader punkt

COPY ./aristote /server_app/aristote
COPY ./server /server_app/server

CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "3000"]
