# Full TeX Live so the thesis compiles exactly as it does locally.
FROM texlive/texlive:latest

# git: history + git-latexdiff temp checkouts.  python3: the diff server.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git python3 ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Fail the build early if the TeX Live image is missing what we rely on.
RUN command -v git-latexdiff && command -v latexmk \
 && command -v latexpand && command -v latexdiff && command -v pdflatex

# git-latexdiff clones the repo into /tmp; give git an identity and trust /app.
RUN git config --global user.email "diff@thesis.local" \
 && git config --global user.name "thesis-diff" \
 && git config --global --add safe.directory /app

WORKDIR /app
COPY . /app

EXPOSE 8080
CMD ["python3", "difftool/server.py", "--host", "0.0.0.0", "--port", "8080"]
