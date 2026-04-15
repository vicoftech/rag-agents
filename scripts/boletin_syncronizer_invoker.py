#!/usr/bin/env python3
"""
Script para invocar Step Function de AWS recorriendo fechas (decrementando por día) 
y secciones (primera, segunda, tercera, cuarta)
"""

import boto3
import json
import time
from datetime import datetime, timedelta
import sys

# Configuración
AWS_REGION = "us-east-1"
AWS_PROFILE = "default"
STEP_FUNCTION_ARN = "arn:aws:states:us-east-1:913123310997:stateMachine:Alerts-BoletinOficialSyncronizer-qa"

# Rango de fechas (descendente por día)
START_DATE = datetime(2026, 4, 15)  # Fecha de inicio (actual)
END_DATE = datetime(2010, 1, 1)     # Fecha final

# Secciones a procesar
SECTIONS = ["primera", "segunda", "tercera", "cuarta"]

def create_step_function_client():
    """Crear cliente de Step Functions"""
    session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
    return session.client('stepfunctions')

def invoke_step_function(sfn_client, date_str, section):
    """Invocar Step Function con fecha y sección específicas"""
    
    payload = {
        "date": date_str,
        "section": section
    }
    
    # Generar nombre único para la ejecución
    execution_name = f"anmat-{date_str}-{section}-{int(time.time())}"
    
    try:
        response = sfn_client.start_execution(
            stateMachineArn=STEP_FUNCTION_ARN,
            name=execution_name,
            input=json.dumps(payload)
        )
        
        execution_arn = response['executionArn']
        print(f"  {'  ' * SECTIONS.index(section)}{section.upper()}: {date_str}")
        print(f"  {'  ' * SECTIONS.index(section)}  ARN: {execution_arn}")
        
        return execution_arn
        
    except Exception as e:
        print(f"  {'  ' * SECTIONS.index(section)}{section.upper()}: ERROR - {str(e)}")
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
                print(f"  {'  ' * 2}  SUCCESS")
                return True
            elif status in ['FAILED', 'TIMED_OUT', 'ABORTED']:
                print(f"  {'  ' * 2}  FAILED: {status}")
                return False
            elif status == 'RUNNING':
                print(f"  {'  ' * 2}  RUNNING... ({int(time.time() - start_time)}s)")
                time.sleep(10)
            else:
                print(f"  {'  ' * 2}  UNKNOWN: {status}")
                time.sleep(10)
                
        except Exception as e:
            print(f"  {'  ' * 2}  ERROR checking status: {str(e)}")
            time.sleep(10)
    
    print(f"  {'  ' * 2}  TIMEOUT")
    return False

def process_date(sfn_client, date):
    """Procesar todas las secciones para una fecha específica"""
    
    date_str = date.strftime('%Y-%m-%d')
    print(f"\n{'='*60}")
    print(f"Procesando fecha: {date_str}")
    print('='*60)
    
    successful_sections = []
    failed_sections = []
    
    for section in SECTIONS:
        print(f"\n  {section.upper()}:")
        
        # Invocar para esta sección
        execution_arn = invoke_step_function(sfn_client, date_str, section)
        
        if not execution_arn:
            failed_sections.append(section)
            continue
        
        # Esperar a que complete
        success = wait_for_completion(sfn_client, execution_arn)
        
        if success:
            successful_sections.append(section)
        else:
            failed_sections.append(section)
        
        # Pequeña pausa entre secciones
        time.sleep(2)
    
    # Resumen del día
    print(f"\n  Resumen {date_str}:")
    print(f"    Exitosas: {successful_sections}")
    print(f"    Fallidas: {failed_sections}")
    
    return len(successful_sections) > 0

def main():
    """Función principal"""
    
    print("Invocando Step Functions por fecha y sección")
    print(f"Región: {AWS_REGION}")
    print(f"Perfil: {AWS_PROFILE}")
    print(f"Rango de fechas: {START_DATE.strftime('%Y-%m-%d')} a {END_DATE.strftime('%Y-%m-%d')}")
    print(f"Secciones: {', '.join(SECTIONS)}")
    print(f"Procesando una ejecución a la vez")
    print("="*60)
    
    # Crear cliente de Step Functions
    sfn_client = create_step_function_client()
    
    if not sfn_client:
        print("ERROR: No se pudo crear cliente de Step Functions")
        sys.exit(1)
    
    # Procesar fechas en orden descendente (día por día)
    current_date = START_DATE
    successful_dates = []
    failed_dates = []
    
    while current_date >= END_DATE:
        print(f"\n{'='*60}")
        print(f"PROCESANDO FECHA: {current_date.strftime('%Y-%m-%d')}")
        print(f"Restantes: {(current_date - END_DATE).days} días")
        print('='*60)
        
        success = process_date(sfn_client, current_date)
        
        if success:
            successful_dates.append(current_date.strftime('%Y-%m-%d'))
            print(f"  RESULTADO: EXITOSO")
        else:
            failed_dates.append(current_date.strftime('%Y-%m-%d'))
            print(f"  RESULTADO: FALLIDO")
        
        # Decrementar un día
        current_date -= timedelta(days=1)
        
        # Pausa entre fechas
        time.sleep(5)
    
    # Resumen final
    print("\n" + "="*60)
    print("RESUMEN FINAL")
    print("="*60)
    print(f"Fechas exitosas: {len(successful_dates)}")
    print(f"Fechas fallidas: {len(failed_dates)}")
    print(f"Total procesadas: {len(successful_dates) + len(failed_dates)}")
    print(f"Completado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if failed_dates:
        print(f"\nFechas fallidas:")
        for date in failed_dates[:10]:  # Mostrar primeras 10
            print(f"  - {date}")
        if len(failed_dates) > 10:
            print(f"  ... y {len(failed_dates) - 10} más")

if __name__ == "__main__":
    main()
