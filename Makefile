.PHONY: help fetch run-baseline run-all docker-build docker-run

help:
	@echo "Targets:"
	@echo "  fetch         - clone PX4 into external/"
	@echo "  run-baseline  - run baseline scenario"
	@echo "  run-all       - run baseline + low_battery"
	@echo "  docker-build  - build docker image"
	@echo "  docker-run    - run all scenarios in docker"

fetch:
	./scripts/fetch_px4.sh

run-baseline:
	python scripts/run_scenario.py --scenario scenarios/baseline.yaml --headless

run-all:
	python scripts/run_all.py --headless

docker-build:
	docker build -t px4-reglab -f docker/Dockerfile .

docker-run:
	docker run --rm -it --net=host -v "$$PWD:/work" -w /work px4-reglab python scripts/run_all.py --headless
