# mobile-use: automate your phone with natural language

<div align="center">

![mobile-use in Action](./doc/linkedin-demo-with-text.gif)

</div>

<div align="center">

![Feature](https://github.com/minitap-ai/mobile-use/actions/workflows/feature.yml/badge.svg)
![Deployment](https://github.com/minitap-ai/mobile-use/actions/workflows/deployment.yml/badge.svg)

[![PyPI version](https://img.shields.io/pypi/v/minitap-mobile-use.svg?color=green)](https://pypi.org/project/minitap-mobile-use/)
[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-yellow)](https://github.com/minitap-ai/mobile-use/blob/main/LICENSE)

[![Discord](https://img.shields.io/discord/1403058278342201394?color=7289DA&label=Discord&logo=discord&logoColor=white&style=for-the-badge)](https://discord.gg/6nSqmQ9pQs)
[![GitHub stars](https://img.shields.io/github/stars/minitap-ai/mobile-use?style=for-the-badge&color=e0a8dd)](https://github.com/minitap-ai/mobile-use/stargazers)

<p align="center">
    <a href="https://discord.gg/6nSqmQ9pQs"><b>Discord</b></a> •
    <a href="https://x.com/minitap_ai?t=iRWtI497UhRGLeCKYQekig&s=09"><b>Twitter / X</b></a>
</p>

</div>

Mobile-use is a powerful, open-source AI agent that controls your Android or IOS device using natural language. It understands your commands and interacts with the UI to perform tasks, from sending messages to navigating complex apps.

> Mobile-use is quickly evolving. Your suggestions, ideas, and reported bugs will shape this project. Do not hesitate to join in the conversation on [Discord](https://discord.gg/6nSqmQ9pQs) or contribute directly, we will reply to everyone! ❤️

## ✨ Features

- 🗣️ **Natural Language Control**: Interact with your phone using your native language.
- 📱 **UI-Aware Automation**: Intelligently navigates through app interfaces.
- 📊 **Data Scraping**: Extract information from any app and structure it into your desired format (e.g., JSON) using a natural language description.
- 🔧 **Extensible & Customizable**: Easily configure different LLMs to power the agents that power mobile-use.

## Benchmarks

<p align="center">
  <img src="./doc/benchmark.jpg" alt="Project banner" />
</p>

We are global number 1 Opensource pass@1 on the AndroidWorld benchmark.

More info here: https://minitap.ai/research/mobile-ai-agents-benchmark

The official leaderboard is available [here](https://docs.google.com/spreadsheets/d/1cchzP9dlTZ3WXQTfYNhh3avxoLipqHN75v1Tb86uhHo/edit?pli=1&gid=0#gid=0)

## 🚀 Getting Started

Ready to automate your mobile experience? Follow these steps to get mobile-use up and running.

1.  **Set up Environment Variables:**
    Copy the example `.env.example` file to `.env` and add your API keys.

    ```bash
    cp .env.example .env
    ```

2.  **(Optional) Customize LLM Configuration:**
    To use different models or providers, create your own LLM configuration file.
    ```bash
    cp llm-config.override.template.jsonc llm-config.override.jsonc
    ```
    Then, edit `llm-config.override.jsonc` to fit your needs.

### Quick Launch (Docker)

> [!NOTE]  
> This quickstart, is only available for Android devices/emulators as of now, and you must have Docker installed.

First:

- Either plug your Android device and enable USB-debugging via the Developer Options
- Or launch an Android emulator

> [!IMPORTANT]  
> At some point, the terminal will HANG, and Maestro will ask you `Maestro CLI would like to collect anonymous usage data to improve the product.`
> It's up to you whether you accept (i.e enter 'Y') or not (i.e. enter 'n').

Then run in your terminal:

1. For Linux/macOS:

```bash
chmod +x mobile-use.sh
./mobile-use.sh \
  "Open Gmail, find first 3 unread emails, and list their sender and subject line" \
  --output-description "A JSON list of objects, each with 'sender' and 'subject' keys"
```

2. For Windows (inside a Powershell terminal):

```powershell
powershell.exe -ExecutionPolicy Bypass -File mobile-use.ps1 `
  "Open Gmail, find first 3 unread emails, and list their sender and subject line" `
  --output-description "A JSON list of objects, each with 'sender' and 'subject' keys"
```

> [!NOTE]  
> If using your own device, make sure to accept the ADB-related connection requests that will pop up on your device.
> Similarly, Maestro will need to install its APK on your device, which will also require you to accept the installation request.

#### 🧰 Troubleshooting

The script will try to connect to your device via IP.  
Therefore, your device **must be connected to the same Wi-Fi network as your computer**.

##### 1. No device IP found

If the script fails with the following message:

```
Could not get device IP. Is a device connected via USB and on the same Wi-Fi network?
```

Then it couldn't find one of the common Wi-Fi interfaces on your device.  
Therefore, you must determine what WLAN interface your phone is using via `adb shell ip addr show up`.
Then add the `--interface <YOUR_INTERFACE_NAME>` option to the script.

##### 2. Failed to connect to <DEVICE_IP>:5555 inside Docker

This is most probably an issue with your firewall blocking the connection. Therefore there is no clear fix for this.

##### 3. Failed to pull GHCR docker images (unauthorized)

Since UV docker images rely on a `ghcr.io` public repositories, you may have an expired token if you used `ghcr.io` before for private repositories.  
Try running `docker logout ghcr.io` and then run the script again.

### Manual Launch (Development Mode)

For developers who want to set up the environment manually:

#### 1. Device Support

Mobile-use currently supports the following devices:

- **Physical Android Phones**: Connect via USB with USB debugging enabled.
- **Android Simulators**: Set up through Android Studio.
- **iOS Simulators**: Supported for macOS users.

> [!NOTE]  
> Physical iOS devices are not yet supported.

#### 2. Prerequisites

For Android:

- **[Android Debug Bridge (ADB)](https://developer.android.com/studio/releases/platform-tools)**: A tool to connect to your device.

For iOS:

- **[Xcode](https://developer.apple.com/xcode/)**: Apple's IDE for iOS development.

Before you begin, ensure you have the following installed:

- **[uv](https://github.com/astral-sh/uv)**: A lightning-fast Python package manager.
- **[Maestro](https://maestro.mobile.dev/getting-started/installing-maestro)**: The framework we use to interact with your device.

#### 3. Installation

1.  **Clone the repository:**

    ```bash
    git clone https://github.com/minitap-ai/mobile-use.git && cd mobile-use
    ```

2.  [**Setup environment variables**](#-getting-started)

3.  **Create & activate the virtual environment:**

    ```bash
    # This will create a .venv directory using the Python version in .python-version
    uv venv

    # Activate the environment
    # On macOS/Linux:
    source .venv/bin/activate
    # On Windows:
    .venv\Scripts\activate
    ```

4.  **Install dependencies:**
    ```bash
    # Sync with the locked dependencies for a consistent setup
    uv sync
    ```

## 👨‍💻 Usage

To run mobile-use, simply pass your command as an argument.

**Example 1: Basic Command**

```bash
python ./src/mobile_use/main.py "Go to settings and tell me my current battery level"
```

**Example 2: Data Scraping**

Extract specific information and get it back in a structured format. For instance, to get a list of your unread emails:

```bash
python ./src/mobile_use/main.py \
  "Open Gmail, find all unread emails, and list their sender and subject line" \
  --output-description "A JSON list of objects, each with 'sender' and 'subject' keys"
```

> [!NOTE]  
> If you haven't configured a specific model, mobile-use will prompt you to choose one from the available options.

## 🔎 Agentic System Overview

<div align="center">

![Graph Visualization](doc/graph.png)

_This diagram is automatically updated from the codebase. This is our current agentic system architecture._

</div>

## ❤️ Contributing

We love contributions! Whether you're fixing a bug, adding a feature, or improving documentation, your help is welcome. Please read our **[Contributing Guidelines](CONTRIBUTING.md)** to get started.

## ⭐ Star History

<p align="center">
  <a href="https://star-history.com/#minitap-ai/mobile-use&Date">
    <img src="https://api.star-history.com/svg?repos=minitap-ai/mobile-use&type=Date" alt="Star History Chart" />
  </a>
</p>

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
