#!/usr/bin/env python3
"""
Extract conversation chunks from chat history.

A chunk is defined as:
- A sequence of consecutive messages from the same user
- Until either another user starts typing, OR
- A pause of more than 1 minute occurs between messages
"""

import json
import argparse
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import re

@dataclass
class Message:
    """Represents a single chat message."""
    timestamp: datetime
    user_id: str
    user_name: str
    text: str
    message_id: Optional[str] = None

@dataclass
class Chunk:
    """Represents a chunk of consecutive messages from the same user."""
    user_id: str
    user_name: str
    messages: List[str]
    start_time: datetime
    end_time: datetime
    duration_seconds: float
    message_count: int
    total_chars: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "user_name": self.user_name,
            "messages": self.messages,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_seconds": self.duration_seconds,
            "message_count": self.message_count,
            "total_chars": self.total_chars
        }

class ChatHistoryParser:
    """Parse chat history and extract chunks."""
    
    def __init__(self, pause_threshold_minutes: int = 1):
        self.pause_threshold = timedelta(minutes=pause_threshold_minutes)
        self.messages: List[Message] = []
        self.chunks: List[Chunk] = []
    
    def parse_telegram_export(self, file_path: str) -> List[Message]:
        """
        Parse Telegram chat export JSON.
        Assumes standard Telegram export format.
        """
        print(f"📱 Parsing Telegram export: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        messages = []
        
        # Handle different export formats
        if 'messages' in data:
            message_list = data['messages']
        elif isinstance(data, list):
            message_list = data
        else:
            raise ValueError("Unknown export format")
        
        for msg_data in message_list:
            # Skip system messages, service messages, etc.
            if msg_data.get('type') != 'message':
                continue
                
            # Skip messages without text
            if not msg_data.get('text'):
                continue
            
            # Extract text (handle different formats)
            text = msg_data.get('text', '')
            if isinstance(text, list):
                # Handle rich text format
                text_parts = []
                for part in text:
                    if isinstance(part, str):
                        text_parts.append(part)
                    elif isinstance(part, dict) and 'text' in part:
                        text_parts.append(part['text'])
                text = ''.join(text_parts)
            
            # Skip empty messages
            if not text.strip():
                continue
            
            # Parse timestamp
            date_str = msg_data.get('date', '')
            try:
                if 'T' in date_str:
                    # ISO format: 2023-12-01T15:30:45
                    timestamp = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                else:
                    # Other formats
                    timestamp = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                print(f"⚠️  Could not parse timestamp: {date_str}")
                continue
            
            # Extract user info
            user_id = str(msg_data.get('from_id', msg_data.get('from', 'unknown')))
            user_name = msg_data.get('from', msg_data.get('from_id', 'Unknown User'))
            message_id = str(msg_data.get('id', ''))
            
            message = Message(
                timestamp=timestamp,
                user_id=user_id,
                user_name=str(user_name),
                text=text.strip(),
                message_id=message_id
            )
            messages.append(message)
        
        print(f"   • Parsed {len(messages)} messages")
        return messages
    
    def parse_whatsapp_export(self, file_path: str) -> List[Message]:
        """
        Parse WhatsApp chat export.
        Format: [DD/MM/YYYY, HH:MM:SS] User Name: Message text
        """
        print(f"💬 Parsing WhatsApp export: {file_path}")
        
        messages = []
        
        # WhatsApp export pattern
        pattern = r'\[(\d{1,2}/\d{1,2}/\d{4}, \d{1,2}:\d{2}:\d{2})\] ([^:]+): (.+)'
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                
                match = re.match(pattern, line)
                if not match:
                    continue
                
                date_str, user_name, text = match.groups()
                
                try:
                    # Parse WhatsApp timestamp format
                    timestamp = datetime.strptime(date_str, '%d/%m/%Y, %H:%M:%S')
                except ValueError:
                    try:
                        timestamp = datetime.strptime(date_str, '%m/%d/%Y, %H:%M:%S')
                    except ValueError:
                        print(f"⚠️  Could not parse timestamp on line {line_num}: {date_str}")
                        continue
                
                message = Message(
                    timestamp=timestamp,
                    user_id=user_name.lower().replace(' ', '_'),
                    user_name=user_name,
                    text=text.strip(),
                    message_id=str(line_num)
                )
                messages.append(message)
        
        print(f"   • Parsed {len(messages)} messages")
        return messages
    
    def auto_detect_and_parse(self, file_path: str) -> List[Message]:
        """Auto-detect file format and parse accordingly."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Check file extension and content
        if file_path.endswith('.json'):
            return self.parse_telegram_export(file_path)
        elif file_path.endswith('.txt'):
            # Try to detect WhatsApp format
            with open(file_path, 'r', encoding='utf-8') as f:
                first_line = f.readline().strip()
                if re.match(r'\[\d{1,2}/\d{1,2}/\d{4}, \d{1,2}:\d{2}:\d{2}\]', first_line):
                    return self.parse_whatsapp_export(file_path)
        
        raise ValueError(f"Could not detect format for file: {file_path}")
    
    def extract_chunks(self, messages: List[Message]) -> List[Chunk]:
        """Extract chunks from messages based on user changes and time gaps."""
        if not messages:
            return []
        
        print(f"\n🔗 Extracting chunks from {len(messages)} messages...")
        
        # Sort messages by timestamp
        messages.sort(key=lambda m: m.timestamp)
        
        chunks = []
        current_chunk_messages = []
        current_user_id = None
        chunk_start_time = None
        
        for i, message in enumerate(messages):
            # Check if we should start a new chunk
            should_start_new_chunk = False
            
            # Reason 1: Different user
            if current_user_id is not None and message.user_id != current_user_id:
                should_start_new_chunk = True
                reason = "user_change"
            
            # Reason 2: Time gap > threshold
            elif (current_chunk_messages and 
                  message.timestamp - messages[i-1].timestamp > self.pause_threshold):
                should_start_new_chunk = True
                reason = "time_gap"
            
            # Reason 3: First message
            elif current_user_id is None:
                should_start_new_chunk = False  # Actually starting first chunk
                reason = "first_message"
            
            # If we need to start a new chunk, save the current one
            if should_start_new_chunk and current_chunk_messages:
                chunk = self._create_chunk(
                    current_user_id,
                    current_chunk_messages,
                    chunk_start_time,
                    messages[i-1].timestamp
                )
                chunks.append(chunk)
                current_chunk_messages = []
            
            # Add message to current chunk
            if not current_chunk_messages:  # Starting new chunk
                chunk_start_time = message.timestamp
            
            current_chunk_messages.append(message)
            current_user_id = message.user_id
        
        # Don't forget the last chunk
        if current_chunk_messages:
            chunk = self._create_chunk(
                current_user_id,
                current_chunk_messages,
                chunk_start_time,
                current_chunk_messages[-1].timestamp
            )
            chunks.append(chunk)
        
        print(f"   • Extracted {len(chunks)} chunks")
        
        # Show statistics
        self._print_chunk_statistics(chunks)
        
        return chunks
    
    def _create_chunk(self, user_id: str, messages: List[Message], 
                     start_time: datetime, end_time: datetime) -> Chunk:
        """Create a Chunk object from a list of messages."""
        message_texts = [msg.text for msg in messages]
        total_chars = sum(len(text) for text in message_texts)
        duration = (end_time - start_time).total_seconds()
        
        return Chunk(
            user_id=user_id,
            user_name=messages[0].user_name,
            messages=message_texts,
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration,
            message_count=len(messages),
            total_chars=total_chars
        )
    
    def _print_chunk_statistics(self, chunks: List[Chunk]):
        """Print statistics about the extracted chunks."""
        if not chunks:
            return
        
        print(f"\n📊 CHUNK STATISTICS:")
        
        # Basic stats
        total_messages = sum(chunk.message_count for chunk in chunks)
        avg_messages_per_chunk = total_messages / len(chunks)
        
        print(f"   • Total chunks: {len(chunks)}")
        print(f"   • Total messages: {total_messages}")
        print(f"   • Avg messages per chunk: {avg_messages_per_chunk:.1f}")
        
        # Message count distribution
        message_counts = [chunk.message_count for chunk in chunks]
        print(f"   • Min messages in chunk: {min(message_counts)}")
        print(f"   • Max messages in chunk: {max(message_counts)}")
        
        # Duration stats
        durations = [chunk.duration_seconds for chunk in chunks if chunk.duration_seconds > 0]
        if durations:
            print(f"   • Avg chunk duration: {sum(durations) / len(durations):.1f}s")
            print(f"   • Max chunk duration: {max(durations):.1f}s")
        
        # User distribution
        user_counts = {}
        for chunk in chunks:
            user_counts[chunk.user_name] = user_counts.get(chunk.user_name, 0) + 1
        
        print(f"   • Users found: {len(user_counts)}")
        for user, count in sorted(user_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
            print(f"     - {user}: {count} chunks")
    
    def save_chunks(self, chunks: List[Chunk], output_path: str):
        """Save chunks to JSON file."""
        print(f"\n💾 Saving {len(chunks)} chunks to: {output_path}")
        
        chunk_data = {
            "metadata": {
                "total_chunks": len(chunks),
                "extraction_time": datetime.now().isoformat(),
                "pause_threshold_minutes": self.pause_threshold.total_seconds() / 60
            },
            "chunks": [chunk.to_dict() for chunk in chunks]
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(chunk_data, f, indent=2, ensure_ascii=False)
        
        print(f"   ✅ Saved successfully!")

def main():
    parser = argparse.ArgumentParser(description="Extract conversation chunks from chat history")
    parser.add_argument(
        "input_file",
        help="Path to chat export file (JSON for Telegram, TXT for WhatsApp)"
    )
    parser.add_argument(
        "--output",
        "-o",
        default="chunks.json",
        help="Output JSON file path (default: chunks.json)"
    )
    parser.add_argument(
        "--pause_threshold",
        "-p",
        type=int,
        default=1,
        help="Pause threshold in minutes to break chunks (default: 1)"
    )
    parser.add_argument(
        "--format",
        choices=["auto", "telegram", "whatsapp"],
        default="auto",
        help="Input file format (default: auto-detect)"
    )
    
    args = parser.parse_args()
    
    try:
        # Initialize parser
        parser = ChatHistoryParser(pause_threshold_minutes=args.pause_threshold)
        
        # Parse messages
        if args.format == "telegram":
            messages = parser.parse_telegram_export(args.input_file)
        elif args.format == "whatsapp":
            messages = parser.parse_whatsapp_export(args.input_file)
        else:
            messages = parser.auto_detect_and_parse(args.input_file)
        
        if not messages:
            print("❌ No messages found in the export file!")
            return 1
        
        # Extract chunks
        chunks = parser.extract_chunks(messages)
        
        if not chunks:
            print("❌ No chunks extracted!")
            return 1
        
        # Save results
        parser.save_chunks(chunks, args.output)
        
        print(f"\n🎉 Successfully extracted {len(chunks)} chunks!")
        print(f"📁 Output saved to: {args.output}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1

if __name__ == "__main__":
    main()