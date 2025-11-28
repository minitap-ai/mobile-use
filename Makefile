.PHONY: help simulator-up simulator-down simulator-list simulator-status test-ios test test-all install setup clean precommit-install precommit

# Default iOS simulator device type
IOS_DEVICE ?= iPhone 17 Pro
IOS_VERSION ?= iOS 26.1

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

simulator-list: ## List all available iOS simulators
	@echo "📱 Available iOS Simulators:"
	@xcrun simctl list devices available | grep -E "iPhone|iPad"

simulator-status: ## Show status of all simulators
	@echo "📱 iOS Simulator Status:"
	@idb list-targets 2>/dev/null || xcrun simctl list devices | grep -E "Booted|Shutdown"

simulator-up: ## Boot an available iOS simulator and export UDID
	@echo "🚀 Starting iOS simulator..."
	@BOOTED_UDID=$$(xcrun simctl list devices | grep "Booted" | grep -E "iPhone|iPad" | head -n 1 | sed -E 's/.*\(([A-F0-9-]+)\).*/\1/'); \
	if [ -n "$$BOOTED_UDID" ]; then \
		echo "✅ Simulator already booted: $$BOOTED_UDID"; \
		echo "export IOS_UDID=$$BOOTED_UDID"; \
		echo "$$BOOTED_UDID" > .ios_udid; \
	else \
		echo "🔍 Finding available $(IOS_DEVICE) simulator..."; \
		UDID=$$(xcrun simctl list devices available | grep "$(IOS_DEVICE)" | grep "$(IOS_VERSION)" | head -n 1 | sed -E 's/.*\(([A-F0-9-]+)\).*/\1/'); \
		if [ -z "$$UDID" ]; then \
			echo "❌ No $(IOS_DEVICE) simulator found with $(IOS_VERSION)"; \
			echo "💡 Try: make simulator-list"; \
			exit 1; \
		fi; \
		echo "⏳ Booting simulator: $$UDID"; \
		xcrun simctl boot $$UDID; \
		echo "⏳ Waiting for simulator to be ready..."; \
		xcrun simctl bootstatus $$UDID -b; \
		echo "✅ Simulator booted successfully!"; \
		echo "export IOS_UDID=$$UDID"; \
		echo "$$UDID" > .ios_udid; \
	fi; \
	echo ""; \
	echo "📝 Run this command to set the environment variable:"; \
	echo "   export IOS_UDID=\$$(cat .ios_udid)"; \
	echo ""; \
	echo "🧪 Or run tests directly with:"; \
	echo "   make test-ios"

simulator-down: ## Shutdown all booted simulators
	@echo "🛑 Shutting down all simulators..."
	@xcrun simctl shutdown all
	@rm -f .ios_udid
	@echo "✅ All simulators shut down"

simulator-open: ## Open Simulator.app
	@echo "📱 Opening Simulator.app..."
	@open -a Simulator

test-ios: ## Run iOS simulator tests (boots simulator if needed)
	@echo "🧪 Running iOS simulator tests..."
	@if [ ! -f .ios_udid ]; then \
		echo "📱 No simulator UDID found, booting one..."; \
		$(MAKE) simulator-up > /dev/null; \
	fi
	@IOS_UDID=$$(cat .ios_udid 2>/dev/null || echo "") && \
	if [ -z "$$IOS_UDID" ]; then \
		echo "❌ Failed to get simulator UDID"; \
		echo "💡 Try: make simulator-up"; \
		exit 1; \
	else \
		echo "📱 Using simulator: $$IOS_UDID"; \
		IOS_UDID=$$IOS_UDID uv run pytest -v -m ios_simulator; \
	fi

test: ## Run all tests except iOS simulator tests
	@echo "🧪 Running all tests (excluding iOS simulator tests)..."
	@uv run pytest -v -m "not ios_simulator"

test-all: ## Run all tests including iOS simulator tests
	@echo "🧪 Running all tests..."
	@$(MAKE) test
	@$(MAKE) test-ios

install: ## Install dependencies
	@echo "📦 Installing dependencies..."
	@uv sync --dev

setup: ## Setup project (install dependencies + pre-commit hooks)
	@echo "🚀 Setting up project..."
	@$(MAKE) install
	@$(MAKE) precommit-install
	@echo ""
	@echo "✅ Setup complete! You're ready to start developing."

lint: ## Run linting checks
	@echo "🔍 Running linting checks..."
	@uv run ruff format --check
	@uv run ruff check

format: ## Format code
	@echo "✨ Formatting code..."
	@uv run ruff format
	@uv run ruff check --fix

typecheck: ## Run type checking
	@echo "🔍 Running type checks..."
	@uv run pyright

precommit-install: ## Install pre-commit hooks
	@echo "🔧 Installing pre-commit hooks..."
	@uv run pre-commit install
	@echo "✅ Pre-commit hooks installed successfully!"
	@echo ""
	@echo "Pre-commit will now run automatically on every commit."
	@echo "To run manually: make precommit"

precommit: ## Run pre-commit hooks manually on all files
	@echo "🔍 Running pre-commit checks..."
	@uv run pre-commit run --all-files

clean: ## Clean up generated files and caches
	@echo "🧹 Cleaning up..."
	@rm -rf .pytest_cache
	@rm -rf .ruff_cache
	@rm -rf **/__pycache__
	@rm -rf .ios_udid
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Cleanup complete"
