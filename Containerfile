FROM public.ecr.aws/lambda/python:3.13

ENV SUMMARY="DynDNS2-compatible DDNS service running on AWS Lambda with Route53 backend." \
    DESCRIPTION="DynDNS2-compatible DDNS service running on AWS Lambda with Route53 backend." \
    NAME=ddns-route53

LABEL summary="$SUMMARY" \
      description="$DESCRIPTION" \
      io.k8s.description="$DESCRIPTION" \
      io.k8s.display-name="DDNS Route53" \
      name="$NAME" \
      version="latest" \
      usage="Container image providing Lambda handlers for the DDNS Route53 service. Set ImageConfig.Command per function." \
      maintainer="Stephen Cuppett steve@cuppett.com" \
      org.opencontainers.image.source="https://github.com/cuppett/aws-route53-ddns" \
      org.opencontainers.image.url="ghcr.io/cuppett/aws-route53-ddns" \
      org.opencontainers.image.documentation="https://github.com/cuppett/aws-route53-ddns/blob/main/README.md"

COPY src/requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

COPY src/ ${LAMBDA_TASK_ROOT}/src/

# Default entry point — overridden per Lambda function via ImageConfig.Command in CloudFormation
CMD ["src.update_handler.handler"]
