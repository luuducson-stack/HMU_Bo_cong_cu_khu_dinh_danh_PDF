"""Repeatable synthetic PDF benchmark; outputs measurements, never patient data."""
import argparse, cProfile, ctypes, hashlib, json, os, platform, statistics, sys, tempfile, time, threading
from pathlib import Path

def peak_rss():
    if os.name != 'nt': return None
    class Counters(ctypes.Structure):
        _fields_=[('cb',ctypes.c_ulong),('PageFaultCount',ctypes.c_ulong)]+[(name,ctypes.c_size_t) for name in ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage']]
    c=Counters();c.cb=ctypes.sizeof(c)
    kernel=ctypes.windll.kernel32;kernel.GetCurrentProcess.restype=ctypes.c_void_p
    ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(kernel.GetCurrentProcess()),ctypes.byref(c),c.cb)
    return c.PeakWorkingSetSize

class TaskMemory:
    """Sample this process and its current descendants, never unrelated OCR processes."""
    def __init__(self):
        self.peak=0;self.stop=threading.Event();self.thread=None
    def sample(self):
        if os.name!='nt':return
        from ctypes import wintypes
        class Entry(ctypes.Structure):
            _fields_=[('dwSize',wintypes.DWORD),('cntUsage',wintypes.DWORD),('th32ProcessID',wintypes.DWORD),('th32DefaultHeapID',ctypes.c_size_t),('th32ModuleID',wintypes.DWORD),('cntThreads',wintypes.DWORD),('th32ParentProcessID',wintypes.DWORD),('pcPriClassBase',wintypes.LONG),('dwFlags',wintypes.DWORD),('szExeFile',wintypes.WCHAR*260)]
        class Counters(ctypes.Structure):
            _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage']]
        kernel=ctypes.windll.kernel32
        kernel.CreateToolhelp32Snapshot.restype=ctypes.c_void_p;kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=kernel.CreateToolhelp32Snapshot(2,0)
        if handle==ctypes.c_void_p(-1).value:return
        parents={};entry=Entry();entry.dwSize=ctypes.sizeof(entry)
        try:
            found=kernel.Process32FirstW(ctypes.c_void_p(handle),ctypes.byref(entry))
            while found:
                parents[entry.th32ProcessID]=entry.th32ParentProcessID
                found=kernel.Process32NextW(ctypes.c_void_p(handle),ctypes.byref(entry))
        finally:kernel.CloseHandle(handle)
        pids={os.getpid()}
        while True:
            extended=pids|{pid for pid,parent in parents.items() if parent in pids}
            if extended==pids:break
            pids=extended
        total=0
        for pid in pids:
            process=kernel.OpenProcess(0x410,False,pid)
            if not process:continue
            try:
                c=Counters();c.cb=ctypes.sizeof(c)
                if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(process),ctypes.byref(c),c.cb):total+=c.WorkingSetSize
            finally:kernel.CloseHandle(process)
        self.peak=max(self.peak,total)
    def __enter__(self):
        def loop():
            while not self.stop.is_set():self.sample();self.stop.wait(.1)
        self.thread=threading.Thread(target=loop,daemon=True);self.thread.start();return self
    def __exit__(self,*exc):
        self.sample();self.stop.set();self.thread.join()

def build_pdf(path, count, kind):
    import fitz
    d=fitz.open()
    for n in range(count):
        p=d.new_page(width=1200 if kind=='largephoto' else 600,height=1600 if kind=='largephoto' else 400)
        p.insert_text((40,60),'Ho ten: NGUYEN VAN AN',fontsize=13)
        p.insert_text((40,120),'Clinical C34 / Glucose 5.2 / Creatinin 95',fontsize=12)
        for i in range(8):p.insert_text((40,160+i*23),f'Clinical observation {i}: stable result 123',fontsize=10)
        if kind=='nativeunique':p.insert_text((40,365),f'Page {n+1}',fontsize=8)
        if kind=='watermark':
            p.insert_text((100,250),'Ho Thi Minh Chau_20260803161916',fontsize=12,morph=(fitz.Point(100,250),fitz.Matrix(1,1).prerotate(30)))
            for i in range(400):p.draw_line((30+(i%80)*6,150+(i//80)*25),(32+(i%80)*6,153+(i//80)*25),color=(0,0,0))
        if kind=='largephoto':
            photo=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,2400,3200),False)
            photo.clear_with(245)
            for row in range(0,3200,64):
                for col in range(0,2400,64):
                    shade=(row//64*19+col//64*31)%220
                    photo.set_rect(fitz.IRect(col,row,min(2400,col+64),min(3200,row+64)),(shade,shade,(shade+17)%240))
            p.insert_image(fitz.Rect(50,300,1150,1500),stream=photo.tobytes('png'))
        if kind=='vector':
            for i in range(50):p.draw_line((30+i*5,145),(32+i*5,148),color=(0,0,0))
    if kind in ('scan','mixed','large'):
        raster=fitz.open()
        for p in d:
            pix=p.get_pixmap(dpi=200,alpha=False)
            target=raster.new_page(width=600,height=400);target.insert_image(target.rect,stream=pix.tobytes('png'))
            if kind=='mixed':target.insert_text((40,20),'Hospital Header',fontsize=8)
        d.close();d=raster
    d.set_metadata({'creationDate':'D:20261028000000','modDate':'D:20261028000000'})
    d.save(path,no_new_id=True);d.close()

def representative_checks(source, product, kind):
    import fitz
    if kind not in ('watermark','largephoto','nativeunique'):return None
    with fitz.open(source/'input.pdf') as original, fitz.open(product) as output:
        assert len(original)==len(output)
        for before,after in zip(original,output):
            for name in before.search_for('NGUYEN VAN AN'):
                masked=after.get_pixmap(dpi=200,clip=name,alpha=False)
                assert sum(masked.samples)/len(masked.samples)>254,'Patient name region not white'
            area=fitz.Rect(40,105,450,125) if kind in ('watermark','nativeunique') else fitz.Rect(100,500,1000,1400)
            if kind=='watermark':
                clean=fitz.open();page=clean.new_page(width=600,height=400)
                page.insert_text((40,120),'Clinical C34 / Glucose 5.2 / Creatinin 95',fontsize=12)
                expected=page.get_pixmap(dpi=200,clip=area,alpha=False)
            else:expected=before.get_pixmap(dpi=200,clip=area,alpha=False)
            actual=after.get_pixmap(dpi=200,clip=area,alpha=False)
            assert len(expected.samples)==len(actual.samples)
            difference=sum(abs(a-b) for a,b in zip(expected.samples,actual.samples))/len(actual.samples)
            assert difference<=1.0,f'Clinical region changed: average channel difference {difference}'
            if kind=='watermark':clean.close()
    return {'name_regions_white':True,'clinical_region_mean_channel_difference_max':1.0,'reference':'clean clinical text for watermark; original image pixels for largephoto'}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source-dir');ap.add_argument('--output',required=True);ap.add_argument('--runs',type=int,default=3);ap.add_argument('--stage',default='all');ap.add_argument('--cases',default='native10,native150,scan10,scan50,mixed10,case50,vector20,large3');ap.add_argument('--warmup',type=int,default=0);ap.add_argument('--profile',action='store_true');ap.add_argument('--workers',type=int)
    args=ap.parse_args()
    if args.runs < 1 or args.warmup < 0:ap.error('runs must be positive and warmup nonnegative')
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(Path(args.source_dir).resolve() if args.source_dir else root))
    import engine,fitz,pypdf,ocr_helper
    if args.workers:
        original=ocr_helper.ocr_pdf_pages
        def configured(*a,**kw):return original(*a,**kw,max_workers=args.workers)
        engine.ocr_pdf_pages=configured
    cases={'native10':(10,'native'),'native150':(150,'native'),'scan10':(10,'scan'),'scan50':(50,'scan'),'mixed10':(10,'mixed'),'case50':(100,'case'),'vector20':(20,'vector'),'large3':(3,'large'),'watermark10':(10,'watermark'),'largephoto2':(2,'largephoto'),'native_unique50':(50,'nativeunique')}
    output={'python':platform.python_version(),'platform':platform.platform(),'cpu_count':os.cpu_count(),'pymupdf':fitz.VersionBind,'pypdf':pypdf.__version__,'source_dir':str(Path(engine.__file__).parent),'runs':args.runs,'warmup_runs':args.warmup,'source_hashes':{name:hashlib.sha256((Path(engine.__file__).parent/name).read_bytes()).hexdigest() for name in ['engine.py','hmu_recognizers.py','ocr_helper.py']},'workers':args.workers,'memory_scope':'peak_python_rss is cumulative OS peak; peak_task_sampled_rss sums Python and live descendant OCR processes sampled every 100ms' ,'cases':{}}
    profile=cProfile.Profile() if args.profile else None
    if profile:profile.enable()
    with tempfile.TemporaryDirectory(prefix='hmu_benchmark_') as temp:
        temp=Path(temp)
        for name in args.cases.split(','):
            count,kind=cases[name];source=temp/name;source.mkdir()
            if kind=='case':
                for i in range(50):build_pdf(source/f'doc_{i:03d}.pdf',2,'native')
            else:build_pdf(source/'input.pdf',count,kind)
            files=sorted(source.glob('*.pdf'))
            actual_pages=0
            for fixture in files:
                with fitz.open(fixture) as check:actual_pages+=len(check)
            assert actual_pages==count,'Benchmark fixture page count differs from declared corpus'
            if kind=='nativeunique':
                with fitz.open(source/'input.pdf') as unique_check:assert len({p.get_text() for p in unique_check})==count
            fingerprint=hashlib.sha256(b''.join(p.read_bytes() for p in files)).hexdigest()
            runs=[]
            for index in range(-args.warmup,args.runs):
                job=temp/f'{name}_{index}';memory=TaskMemory();memory.__enter__();start=time.perf_counter()
                if kind=='case':engine.prepare_case(source,job,study_id='BENCH')
                else:engine.prepare(source/'input.pdf',job,study_id='BENCH')
                prepared=time.perf_counter()
                if kind=='case':products=engine.export_case(job,approve_all=True)['outputs']
                else:products=[str(engine.export(job,approve_all=True)[0])]
                exported=time.perf_counter();memory.__exit__()
                checks=representative_checks(source,products[0],kind)
                if index < 0:continue
                runs.append({'prepare_seconds':prepared-start,'export_seconds':exported-prepared,'total_seconds':exported-start,'peak_python_rss_bytes':peak_rss(),'peak_task_sampled_rss_bytes':memory.peak,'job_bytes':sum(p.stat().st_size for p in job.rglob('*') if p.is_file()),'output_bytes':sum(Path(product).stat().st_size for product in products)})
            output['cases'][name]={'pages':count,'corpus_sha256':fingerprint,'ground_truth_checks':checks,'measurements':runs,'median_prepare_seconds':statistics.median(r['prepare_seconds'] for r in runs),'median_export_seconds':statistics.median(r['export_seconds'] for r in runs),'median_total_seconds':statistics.median(r['total_seconds'] for r in runs)}
            print(name,json.dumps(output['cases'][name]),flush=True)
            target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(output,indent=2),encoding='utf-8')
    if profile:profile.disable();profile.dump_stats(str(Path(args.output).with_suffix('.prof')))
if __name__=='__main__':main()
