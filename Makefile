#!make
include Makefile.env

# Put it first so that "make" without argument is like "make help".
build: docker-build build-date
release: docker-build build-date docker-release

.PHONY: docker-build build-date docker-release

docker-build:
	docker build --build-arg VERSION="${version}" \
				 -t "${CONTAINER_REPOSITORY}:${version}" \
				 -t "${CONTAINER_REGISTRY}/${CONTAINER_REPOSITORY}:${version}" \
				 .
	docker image prune -f

docker-release:
	docker push ${CONTAINER_REGISTRY}/${CONTAINER_REPOSITORY}:${version}

build-date:
	# Ensures there is always an asset to upload
	mkdir -p build
	date > build/build-date
