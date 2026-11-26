# NeuralTask — AI Task Intelligence Platform

A sleek, dark-themed AI Task Management web application.

## Project Structure

```
neuraltask/
├── index.html    # Main HTML structure
├── styles.css    # All styling (design tokens, components, responsive)
├── main.js       # Application logic (task management, 3D canvas, terminal)
└── README.md     # This file
```

## Features

- 🤖 AI-powered terminal interface for task management
- 🌐 3D animated background using Three.js
- 🌙 Dark / Light theme toggle
- 📊 Weekly activity chart
- ⚡ Task prioritization (high / med / low)
- 💡 AI suggestions engine

## Usage

Open `index.html` in a browser. No build step required.

### Terminal Commands

| Command         | Description                 |
|-----------------|-----------------------------|
| `add <task>`    | Add a new task               |
| `show`          | List all tasks               |
| `done <n>`      | Mark task #n as complete     |
| `ai`            | Run AI analysis on tasks     |
| `exit`          | Shut down the agent          |

## Dependencies (CDN)

- [Three.js r128](https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js)
- [Space Grotesk, JetBrains Mono, Instrument Serif](https://fonts.google.com/)
