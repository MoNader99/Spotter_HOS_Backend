import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from .models import Trip, DrivingLog, Log
from .serializers import TripSerializer, DrivingLogSerializer

class TripConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.trip_id = self.scope['url_route']['kwargs'].get('trip_id')
        self.room_group_name = f'trip_{self.trip_id}' if self.trip_id else 'trips'

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        message = text_data_json['message']

        # Send message to room group
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'trip_message',
                'message': message
            }
        )

    async def trip_message(self, event):
        message = event['message']

        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'message': message
        }))

    async def trip_update(self, event):
        # Send trip update to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'trip_update',
            'trip': event['trip']
        }))

    async def log_update(self, event):
        # Send log update to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'log_update',
            'log': event['log']
        }))

class TripsConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_group_name = 'all_trips'

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        message = text_data_json.get('message', '')

        # Send message to room group
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'trips_message',
                'message': message
            }
        )

    async def trips_message(self, event):
        message = event['message']

        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'message': message
        }))

    async def trip_created(self, event):
        # Send trip created notification to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'trip_created',
            'trip': event['trip']
        }))

    async def trip_updated(self, event):
        # Send trip updated notification to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'trip_updated',
            'trip': event['trip']
        }))

class LogConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.trip_id = self.scope['url_route']['kwargs']['trip_id']
        self.room_group_name = f'logs_{self.trip_id}'

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        message = text_data_json['message']

        # Send message to room group
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'log_message',
                'message': message
            }
        )

    async def log_message(self, event):
        message = event['message']

        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'message': message
        })) 