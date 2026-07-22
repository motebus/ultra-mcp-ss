#!/bin/bash
CI_REGISTRY_USER=$1
CI_REGISTRY_PASSWORD=$2
IMAGE_NAME=$3
IMAGE_VERSION=$4

docker logout
docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD
docker build --pull --no-cache -t $IMAGE_NAME:latest .
docker push $IMAGE_NAME:latest

if [ -n "$IMAGE_VERSION" ]
then
  docker tag $IMAGE_NAME:latest $IMAGE_NAME:$IMAGE_VERSION
  docker push $IMAGE_NAME:$IMAGE_VERSION
fi

echo "Build image finished."
