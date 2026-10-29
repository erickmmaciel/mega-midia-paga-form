FROM python:3.12-slim
WORKDIR /app
COPY automacao/ automacao/
COPY painel/ painel/
ENV PYTHONUNBUFFERED=1 ESTADO_PATH=/data/estado.json TZ=America/Porto_Velho
VOLUME /data
EXPOSE 8080
CMD ["python3", "automacao/servidor.py"]
