#!/usr/bin/env python3
"""
Script para invocar Step Function de AWS para procesar años y páginas de ANMAT
"""

import boto3
import json
import time
from datetime import datetime
import sys

# Configuración
AWS_REGION = "us-east-1"
AWS_PROFILE = "default"
STEP_FUNCTION_ARN = "arn:aws:states:us-east-1:913123310997:stateMachine:rag-anmat-to-s3writer-qa"

# Rango de años (descendente)
START_YEAR = 2026
END_YEAR = 2010

def create_step_function_client():
    """Crear cliente de Step Functions"""
    session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
    return session.client('stepfunctions')

def invoke_step_function(sfn_client, year, page_start, page_end):
    """Invocar Step Function con parámetros específicos"""
    
    payload = {
        "year": str(year),
        "page_start": page_start,
        "page_end": page_end
    }
    
    try:
        response = sfn_client.start_execution(
            stateMachineArn=STEP_FUNCTION_ARN,
            name=f"anmat-{year}-page-{page_start}-{page_end}-{int(time.time())}",
            input=json.dumps(payload)
        )
        
        execution_arn = response['executionArn']
        print(f"✅ Iniciada ejecución para año {year}, páginas {page_start}-{page_end}")
        print(f"   ARN: {execution_arn}")
        
        return execution_arn
        
    except Exception as e:
        print(f"❌ Error invocando Step Function para año {year}: {str(e)}")
        return None

def wait_for_completion(sfn_client, execution_arn, timeout=300):
    """Esperar a que complete la ejecución"""
    
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            response = sfn_client.describe_execution(
                executionArn=execution_arn
            )
            
            status = response['status']
            
            if status == 'SUCCEEDED':
                print(f"✅ Ejecución completada exitosamente")
                return True
            elif status in ['FAILED', 'TIMED_OUT', 'ABORTED']:
                print(f"❌ Ejecución falló con status: {status}")
                return False
            elif status == 'RUNNING':
                print(f"⏳ Ejecutando... ({int(time.time() - start_time)}s)")
                time.sleep(10)
            else:
                print(f"⚠️ Status desconocido: {status}")
                time.sleep(10)
                
        except Exception as e:
            print(f"❌ Error verificando estado: {str(e)}")
            time.sleep(10)
    
    print(f"⏰ Timeout esperando ejecución")
    return False

def process_year(sfn_client, year):
    """Procesar todas las páginas de un año hasta has_more=false"""
    
    print(f"\n📅 Procesando año {year}")
    print("=" * 50)
    
    page_start = 1
    page_end = 1
    has_more = True
    
    while has_more:
        # Invocar para el rango de páginas actual
        execution_arn = invoke_step_function(sfn_client, year, page_start, page_end)
        
        if not execution_arn:
            print(f"❌ No se pudo iniciar ejecución para año {year}, páginas {page_start}-{page_end}")
            return False
        
        # Esperar a que complete
        success = wait_for_completion(sfn_client, execution_arn)
        
        if not success:
            print(f"❌ Falló ejecución para año {year}, páginas {page_start}-{page_end}")
            return False
        
        # Obtener resultado para verificar has_more
        try:
            response = sfn_client.get_execution_history(
                executionArn=execution_arn,
                maxResults=1,
                reverseOrder=True
            )
            
            if response['events']:
                output = response['events'][0].get('stateExitedEventDetails', {}).get('output')
                if output:
                    result = json.loads(output)
                    has_more = result.get('has_more', False)
                    
                    if has_more:
                        # Incrementar para el siguiente lote
                        page_start = page_end + 1
                        page_end = page_start
                        print(f"📄 Continuando con página {page_start} (has_more=true)")
                    else:
                        print(f"🏁 Completado año {year} (has_more=false)")
                        
        except Exception as e:
            print(f"⚠️ Error obteniendo resultado: {str(e)}")
            # Asumir que hay más para no detener el proceso
            has_more = True
        
        # Pequeña pausa entre ejecuciones
        time.sleep(2)
    
    return True

def main():
    """Función principal"""
    
    print("🚀 Iniciando procesamiento de ANMAT via Step Functions")
    print(f"📍 Región: {AWS_REGION}")
    print(f"👤 Perfil: {AWS_PROFILE}")
    print(f"📊 Rango de años: {START_YEAR} a {END_YEAR}")
    print(f"🔄 Procesando una ejecución a la vez")
    print("=" * 60)
    
    # Crear cliente de Step Functions
    sfn_client = create_step_function_client()
    
    if not sfn_client:
        print("❌ No se pudo crear cliente de Step Functions")
        sys.exit(1)
    
    # Procesar años en orden descendente
    successful_years = []
    failed_years = []
    
    for year in range(START_YEAR, END_YEAR - 1, -1):
        print(f"\n🎯 Iniciando procesamiento del año {year}")
        
        success = process_year(sfn_client, year)
        
        if success:
            successful_years.append(year)
            print(f"✅ Año {year} completado exitosamente")
        else:
            failed_years.append(year)
            print(f"❌ Falló procesamiento del año {year}")
        
        # Pausa entre años
        time.sleep(5)
    
    # Resumen final
    print("\n" + "=" * 60)
    print("📊 RESUMEN FINAL")
    print("=" * 60)
    print(f"✅ Años exitosos: {len(successful_years)}")
    print(f"   {successful_years}")
    print(f"❌ Años fallidos: {len(failed_years)}")
    print(f"   {failed_years}")
    print(f"🏁 Procesamiento completado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()
