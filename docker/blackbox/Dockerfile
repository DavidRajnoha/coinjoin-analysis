# Blackbox CoinJoin Sudoku + chain attribution on mainnet JoinMarket coinjoins.
# Build from the repository root:
#   docker build -f docker/blackbox/Dockerfile -t jm-blackbox .
FROM python:3.12-slim

RUN pip install --no-cache-dir numpy==2.2.6 pandas==2.2.3 Jinja2==3.1.6 pyvis==0.3.2 ijson==3.5.1

WORKDIR /app
COPY joinmarket/ joinmarket/
COPY scripts/parallel_blackbox.py scripts/transform_blocksci_to_blocks.py scripts/
COPY analysis_output/augment_corpus.py analysis_output/
COPY docker/blackbox/ docker/blackbox/
RUN chmod -R a+rX /app && chmod +x docker/blackbox/entrypoint.sh && ln -s /work/subset_cache /app/subset_cache

ENV PYTHONUNBUFFERED=1
VOLUME ["/data", "/work"]
ENTRYPOINT ["docker/blackbox/entrypoint.sh"]
