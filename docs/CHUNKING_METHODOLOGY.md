# Chunking Methodology and Testing Framework

## Core Chunking Concept

A **chunk** is a sequence of consecutive messages from the same user that ends when:
1. A different user starts typing, OR
2. A pause of more than 1 minute occurs

## Training Data Generation

Given a conversation like: `A1 A2 A3 B1 B2 B3 B4` (where A1, A2 = messages from user A, etc.)

We generate examples for **every message** to determine if the user is done or will continue:

- `A1` → **INCOMPLETE** (user A continues with A2)
- `A1 A2` → **INCOMPLETE** (user A continues with A3) 
- `A1 A2 A3` → **COMPLETE** (user A is done, user B takes over)
- `B1` → **INCOMPLETE** (user B continues with B2)
- `B1 B2` → **INCOMPLETE** (user B continues with B3)
- `B1 B2 B3` → **INCOMPLETE** (user B continues with B4)
- `B1 B2 B3 B4` → **COMPLETE** (user B is done)

This gives us 7 training examples from one conversation sequence.

## Context Window Testing

To test if more context helps chunking decisions:

1. Take the same examples as above
2. **Add full chunks of conversation history** before the messages being evaluated
3. Test with different amounts of context:
   - **Small**: 1 previous chunk
   - **Medium**: 3 previous chunks  
   - **Large**: 10 previous chunks

## Expected Outcome

Models with more context should make better decisions about whether a user has completed their thought, leading to higher accuracy on the test examples.

## Key Insight

Each message sequence has a **ground truth label** (COMPLETE/INCOMPLETE) based on what actually happened in the real conversation. This allows us to measure accuracy and compare different approaches.