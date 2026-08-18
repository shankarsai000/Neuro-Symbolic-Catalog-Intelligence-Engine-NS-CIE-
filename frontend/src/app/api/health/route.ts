import { NextResponse } from "next/server";

export async function GET() {
  return NextResponse.json({
    status: "ok",
    service: "NS-CIE Frontend",
    timestamp: new Date().toISOString(),
  });
}
