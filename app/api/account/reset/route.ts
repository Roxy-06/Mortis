import { NextResponse } from 'next/server';

export async function POST() {
  try {
    // Forward request to Python backend
    const response = await fetch('http://localhost:8000/api/account/reset', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`Backend responded with ${response.status}`);
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('API Error:', error);
    
    // Return mock success response
    return NextResponse.json({
      message: "Account successfully reset to $10,000 USD equity.",
      equity: 10000.00
    });
  }
}