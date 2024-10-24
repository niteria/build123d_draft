.PHONY: all

model_files := $(wildcard tests/models/test_*.py)

%.html: %.md
	pandoc -s -t html5 $< > $@

tutorial.md: templates/tutorial.md
	python build_template.py $< > $@

README.md: README.header.md $(model_files)
	python build.py

all: tutorial.html README.md
