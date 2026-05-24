ACCOUNT_ID ?= 123456789012
REGION     ?= us-east-1
PROFILE    ?= default
REPO_NAME  ?= ddns-route53
IMAGE_TAG  ?= latest

ECR_URI    := $(ACCOUNT_ID).dkr.ecr.$(REGION).amazonaws.com/$(REPO_NAME)
IMAGE_URI  := $(ECR_URI):$(IMAGE_TAG)

AWS        := aws --profile $(PROFILE) --region $(REGION)

.PHONY: install test build push deploy-ecr deploy-service help

help:
	@echo "Targets:"
	@echo "  install       Install test dependencies"
	@echo "  test          Run unit tests"
	@echo "  build         Build container image with podman"
	@echo "  push          Push image to ECR"
	@echo "  deploy-service Deploy main service stack"
	@echo ""
	@echo "Note: ECR repository is managed by the aws-codebuild-podman or aws-ecr-mirror project."
	@echo ""
	@echo "Variables (override with make VAR=value):"
	@echo "  ACCOUNT_ID  $(ACCOUNT_ID)"
	@echo "  REGION      $(REGION)"
	@echo "  PROFILE     $(PROFILE)"
	@echo "  REPO_NAME   $(REPO_NAME)"
	@echo "  IMAGE_TAG   $(IMAGE_TAG)"

install:
	python3 -m pip install -r tests/requirements.txt

test:
	python -m pytest tests/ -v

build:
	podman build --platform linux/arm64 -t $(REPO_NAME):$(IMAGE_TAG) -f Containerfile .

push: build
	$(AWS) ecr get-login-password | \
		podman login --username AWS --password-stdin $(ACCOUNT_ID).dkr.ecr.$(REGION).amazonaws.com
	podman tag $(REPO_NAME):$(IMAGE_TAG) $(IMAGE_URI)
	podman push $(IMAGE_URI)

deploy-service:
	$(AWS) cloudformation deploy \
		--template-file cloudformation/ddns_service.yaml \
		--stack-name ddns-route53 \
		--capabilities CAPABILITY_NAMED_IAM \
		--parameter-overrides ImageUri=$(IMAGE_URI)
