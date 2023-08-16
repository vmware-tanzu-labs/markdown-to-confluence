#!make
include Makefile.env

# Put it first so that "make" without argument is like "make help".
build: docker-build
release: docker-build docker-release

.PHONY: docker-build docker-release

docker-build:
	docker build --build-arg VERSION="${version}" \
				 -t "${CONTAINER_REPOSITORY}:${version}" \
				 -t "${CONTAINER_REGISTRY}/${CONTAINER_REPOSITORY}:${version}" \
				 .
	docker image prune -f

docker-release:
	docker push ${CONTAINER_REGISTRY}/${CONTAINER_REPOSITORY}:${version}
