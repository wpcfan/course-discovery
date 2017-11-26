.DEFAULT_GOAL := test
NODE_BIN=$(CURDIR)/node_modules/.bin

.PHONY: accept clean clean_static compile_translations detect_changed_source_translations dummy_translations extract_translations \
	fake_translations help html_coverage migrate open-devstack production-requirements pull_translations quality requirements.js \
	requirements start-devstack static stop-devstack test validate validate_translations docs  static.dev static.watch

include .travis/docker.mk

# Generates a help message. Borrowed from https://github.com/pydanny/cookiecutter-djangopackage.
help: ## Display this help message
	@echo "Please use \`make <target>\` where <target> is one of"
	@perl -nle'print $& if m{^[\.a-zA-Z_-]+:.*?## .*$$}' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m  %-25s\033[0m %s\n", $$1, $$2}'

static: ## Gather all static assets for production
	$(NODE_BIN)/webpack --config webpack.config.js --display-error-details --progress --optimize-minimize
	python manage.py collectstatic --noinput
	python manage.py compress -v3 --force

static.dev:
	$(NODE_BIN)/webpack --config webpack.config.js --display-error-details --progress

static.watch:
	$(NODE_BIN)/webpack --config webpack.config.js --display-error-details --progress --watch

clean_static: ## Remove all generated static files
	rm -rf course_discovery/assets/ course_discovery/static/bundles/

clean: ## Delete generated byte code and coverage reports
	find . -name '*.pyc' -delete
	coverage erase

requirements.js: ## Install JS requirements for local development
	cnpm install
	$(NODE_BIN)/bower install --allow-root

requirements: requirements.js ## Install Python and JS requirements for local development
	pip install -r requirements/local.txt

production-requirements: ## Install Python and JS requirements for production
	pip install -r requirements.txt
	npm config set registry https://registry.npm.taobao.org
	npm install --production
	$(NODE_BIN)/bower install --allow-root --production

test: clean ## Run tests and generate coverage report
	## The node_modules .bin directory is added to ensure we have access to Geckodriver.
	PATH="$(NODE_BIN):$(PATH)" coverage run -m pytest --durations=25
	coverage combine
	coverage report

quality: ## Run pep8 and Pylint
	isort --check-only --recursive acceptance_tests/ course_discovery/
	pep8 --config=.pep8 acceptance_tests course_discovery *.py
	pylint --rcfile=pylintrc acceptance_tests course_discovery *.py

validate: quality test ## Run tests and quality checks

migrate: ## Apply database migrations
	python manage.py migrate --noinput
	python manage.py install_es_indexes

html_coverage: ## Generate and view HTML coverage report
	coverage html && open htmlcov/index.html

extract_translations: ## Extract strings to be translated, outputting .mo files
	# NOTE: We need PYTHONPATH defined to avoid ImportError(s) on Travis CI.
	cd course_discovery && PYTHONPATH="..:${PYTHONPATH}" i18n_tool extract --verbose
	cd course_discovery && PYTHONPATH="..:${PYTHONPATH}" i18n_tool generate --verbose

dummy_translations: ## Generate dummy translation (.po) files
	cd course_discovery && i18n_tool dummy

compile_translations: ## Compile translation files, outputting .po files for each supported language
	python manage.py compilemessages

fake_translations: extract_translations dummy_translations compile_translations ## Generate and compile dummy translation files

pull_translations: ## Pull translations from Transifex
	tx pull -af --mode reviewed

start-devstack: ## Run a local development copy of the server
	docker-compose up

stop-devstack: ## Shutdown the local development server
	docker-compose down

open-devstack: ## Open a shell on the server started by start-devstack
	docker-compose up -d
	docker exec -it course-discovery env TERM=$(TERM) /edx/app/discovery/devstack.sh open

accept: ## Run acceptance tests
	nosetests --with-ignore-docstrings -v acceptance_tests

detect_changed_source_translations: ## Check if translation files are up-to-date
	cd course_discovery && i18n_tool changed

validate_translations: fake_translations detect_changed_source_translations ## Install fake translations and check if translation files are up-to-date

docs:
	cd docs && make html
