# Trinetra Agent - Setup and Run Guide

Welcome to the Trinetra Agent project. This guide will help you set up the project locally from scratch, create necessary environments, install dependencies, and start the system.

## Prerequisites

Before starting, ensure you have the following installed on your system:
- **Python 3.10+**
- **Redis Server** (needs to be running locally on port `6379`)
- **Git**

You also need a **Supabase** project and a **Groq API key**.

---

## 1. Clone the Repository

Clone the project to your local machine and navigate into the root directory:

```bash
git clone <repository_url>
cd Trinetra-Agent
```

---

## 2. Environment Configuration (.env files)

This project requires environment variables at the root and in the `backend` directory. We have provided `.env.example` files to help you set these up.

1. **Root `.env`**:
   Copy `.env.example` to `.env` in the root of the project:
   ```bash
   cp .env.example .env
   ```
   Open `.env` and fill in your `GROQ_API_KEY`, `SUPABASE_URL`, and `SUPABASE_KEY`.

2. **Backend `.env`**:
   Copy the example file to the `backend/` directory:
   ```bash
   cp backend/.env.example backend/.env
   ```
   Open `backend/.env` and fill in your `SUPABASE_URL` and `SUPABASE_KEY`.

---

## 3. Setup Python Virtual Environments

The project is split into the main backend and the AI agents. You will need to create two separate virtual environments and install dependencies for both.

### A. Backend Setup
Navigate to the `backend` folder, create a virtual environment, and install dependencies:

```bash
cd backend
python3 -m venv venv

# Activate the virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
# venv\Scripts\activate

# Install requirements
pip install -r requirements.txt

# Return to root directory
cd ..
```

### B. Agents Setup
Navigate to the `agents` folder, create a virtual environment, and install dependencies:

```bash
cd agents
python3 -m venv venv

# Activate the virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
# venv\Scripts\activate

# Install requirements
pip install -r requirements.txt

# Return to root directory
cd ..
```

---

## 4. Ensure Redis is Running

Ensure your local Redis server is active. On macOS, if installed via Homebrew, you can start it with:

```bash
brew services start redis
```

(The default URL expected by the system is `redis://localhost:6379`)

---

## 5. Running the Application

To run the application, you need to start both the FastAPI backend and the AI Agent workers. It is recommended to run these in separate terminal windows.

### Terminal 1: Start the Backend Web Server
```bash
cd backend
source venv/bin/activate

# Start the FastAPI server using Uvicorn
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Terminal 2: Start the AI Agents Pipeline
```bash
cd agents
source venv/bin/activate

# Execute the start script to boot up all AI agents
./start_all_agents.sh

# Alternatively, if you want them to automatically restart on file changes:
# ./start_with_watchdog.sh
```

---

## Ready!

Once both the backend and agents are running successfully, your backend will be accessible at `http://localhost:8000`. You can test the application or connect it to your frontend (e.g., dev server at `http://localhost:5173`).