#!/usr/bin/env python3
# filepath: c:\Users\BhaveshP3\Downloads\payment_app\test_terminal.py
"""
Terminal interface for Payment Collection AI Agent
Allows interactive conversation with the chatbot one message at a time.
"""

from agent import Agent


def main():
    print("=" * 70)
    print("Payment Collection AI Agent - Terminal Interface")
    print("=" * 70)
    print("Type 'quit', 'exit', or 'bye' to end the session.")
    print("=" * 70)
    print()

    # Initialize the agent
    agent = Agent()

    # Start the conversation
    print("Bot: Starting new payment collection session...\n")

    while True:
        # Get user input
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nSession ended by user.")
            break

        # Check for exit commands
        if user_input.lower() in ("quit", "exit", "bye"):
            print("\nBot: Thank you for using our payment collection service. Goodbye!\n")
            break

        # Skip empty inputs
        if not user_input:
            continue

        # Get agent response
        try:
            response = agent.next(user_input)
            print(f"\nBot: {response['message']}\n")
        except Exception as e:
            print(f"\nError: {e}\n")
            print("An error occurred. Please try again or contact support.\n")


if __name__ == "__main__":
    main()
