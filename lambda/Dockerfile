# Dockerfile for AWS Lambda Container Image
# Base: official AWS Lambda Python 3.13 Image
# Contains Lambda Runtime Interface Client (RIC) — no separate HTTP-Server necessary

FROM public.ecr.aws/lambda/python:3.13
# public.ecr.aws/lambda/python:3.13 = AWS Base Image for Python Lambda
# Already Ccontains: Python 3.13, the Lambda Runtime Interface Client, AWS CA Certificates
# Alternatively you could use a slim Python image and install RIC yourself, but AWS Base Image ist easier and guaranteed to work with Lambda

RUN dnf install -y \
    mesa-libGL \
    glib2 \
    && dnf clean all
# libGL = OpenGL Bibliothek for OpenCV
# libgthread = Threading-Bibliothek for GLib
# yum clean all = delete cache to keep image size small
# Lambda Base Image uses Linux 2, therefore yum instead of apt

# Python Dependencies
COPY requirements.txt .
RUN pip install \
    --no-cache-dir \
    --target /var/task \
    -r requirements.txt
# --no-cache-dir = means no pip Cache im Image. saves about ~50MB
# --target /var/task = Lambda expects Code and Dependencies in /var/task
# requirements.txt enthält opencv-python-headless no GUI for smaller image size, onnxruntime, numpy

# Application Code
COPY core/ /var/task/core/
# copies the whole core/ folder to /var/task/core/
# Lambda searches the handler then in /var/task/core/handler.py

# ONNX Model
COPY models/ /var/task/models/
# Model isl ocated at /var/task/models/car_damage_v1.onnx
# corresponds to MODEL_PATH = "/var/task/models/car_damage_v1.onnx" in config.py

# Lambda Handler
CMD ["core.handler.lambda_handler"]
# Format: {Modul}.{Datei}.{Function}
# Must exactely correspond with handler in lambda.tf:
# handler = "core.handler.lambda_handler"
